from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.utils import timezone
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import eventstore
from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import EnvironmentMixin, region_silo_endpoint
from sentry.api.bases import GroupEndpoint
from sentry.api.exceptions import ResourceDoesNotExist
from sentry.api.helpers.environments import get_environments
from sentry.api.helpers.events import get_direct_hit_response, get_query_builder_for_group
from sentry.api.paginator import GenericOffsetPaginator
from sentry.api.serializers import EventSerializer, SimpleEventSerializer, serialize
from sentry.api.utils import get_date_range_from_params
from sentry.eventstore.models import Event
from sentry.exceptions import InvalidParams, InvalidSearchQuery
from sentry.search.utils import InvalidQuery, parse_query

if TYPE_CHECKING:
    from sentry.models.environment import Environment
    from sentry.models.group import Group


class NoResults(Exception):
    pass


class GroupEventsError(Exception):
    pass


@region_silo_endpoint
class GroupEventsEndpoint(GroupEndpoint, EnvironmentMixin):
    publish_status = {
        "GET": ApiPublishStatus.UNKNOWN,
    }
    owner = ApiOwner.ISSUES

    def get(self, request: Request, group: Group) -> Response:
        """
        List an Issue's Events
        ``````````````````````

        This endpoint lists an issue's events.
        :qparam bool full: if this is set to true then the event payload will
                           include the full event body, including the stacktrace.
                           Set to 1 to enable.

        :qparam bool sample: return events in pseudo-random order. This is deterministic,
                             same query will return the same events in the same order.

        :pparam string issue_id: the ID of the issue to retrieve.

        :auth: required
        """

        try:
            environments = get_environments(request, group.project.organization)
            query = self._get_search_query(request, group, environments)
        except InvalidQuery as exc:
            return Response({"detail": str(exc)}, status=400)
        except (NoResults, ResourceDoesNotExist):
            return Response([])

        try:
            start, end = get_date_range_from_params(request.GET, optional=True)
        except InvalidParams as e:
            raise ParseError(detail=str(e))

        try:
            return self._get_events_snuba(request, group, environments, query, start, end)
        except GroupEventsError as exc:
            raise ParseError(detail=str(exc))

    def _get_events_snuba(
        self,
        request: Request,
        group: Group,
        environments: Sequence[Environment],
        query: str | None,
        start: datetime | None,
        end: datetime | None,
    ) -> Response:
        default_end = timezone.now()
        default_start = default_end - timedelta(days=90)
        params = {
            "project_id": [group.project_id],
            "organization_id": group.project.organization_id,
            "start": start if start else default_start,
            "end": end if end else default_end,
        }
        referrer = f"api.group-events.{group.issue_category.name.lower()}"

        direct_hit_resp = get_direct_hit_response(
            request, query, params, f"{referrer}.direct-hit", group
        )
        if direct_hit_resp:
            return direct_hit_resp

        if environments:
            params["environment"] = [env.name for env in environments]

        full = request.GET.get("full") in ("1", "true")
        sample = request.GET.get("sample") in ("1", "true")

        if sample:
            orderby = "sample"
        else:
            orderby = None

        def data_fn(offset: int, limit: int) -> Any:
            try:
                snuba_query = get_query_builder_for_group(
                    request.GET.get("query", ""),
                    params,
                    group,
                    limit=limit,
                    offset=offset,
                    orderby=orderby,
                )
            except InvalidSearchQuery as e:
                raise ParseError(detail=str(e))
            results = snuba_query.run_query(referrer=referrer)
            results = [
                Event(
                    event_id=evt["id"],
                    project_id=evt["project.id"],
                    snuba_data={
                        "event_id": evt["id"],
                        "group_id": evt["issue.id"],
                        "project_id": evt["project.id"],
                        "timestamp": evt["timestamp"],
                    },
                )
                for evt in results["data"]
            ]
            if full:
                eventstore.backend.bind_nodes(results)

            return results

        serializer = EventSerializer() if full else SimpleEventSerializer()
        return self.paginate(
            request=request,
            on_results=lambda results: serialize(results, request.user, serializer),
            paginator=GenericOffsetPaginator(data_fn=data_fn),
        )

    def _get_search_query(
        self, request: Request, group: Group, environments: Sequence[Environment]
    ) -> str | None:
        raw_query = request.GET.get("query")

        if raw_query:
            query_kwargs = parse_query([group.project], raw_query, request.user, environments)
            query = query_kwargs.pop("query", None)
        else:
            query = None

        return query
