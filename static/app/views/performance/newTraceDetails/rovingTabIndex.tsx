import type {TraceTree, TraceTreeNode} from './traceTree';

export interface RovingTabIndexState {
  index: number | null;
  items: number | null;
  node: TraceTreeNode<TraceTree.NodeValue> | null;
}

export type RovingTabIndexAction =
  | {
      index: number | null;
      items: number;
      node: TraceTreeNode<TraceTree.NodeValue> | null;
      type: 'initialize';
    }
  | {index: number; node: TraceTreeNode<TraceTree.NodeValue>; type: 'set index'};

export type RovingTabIndexUserActions = 'next' | 'previous' | 'last' | 'first';

export function rovingTabIndexReducer(
  state: RovingTabIndexState,
  action: RovingTabIndexAction
): RovingTabIndexState {
  switch (action.type) {
    case 'initialize': {
      return {index: action.index, items: action.items, node: action.node};
    }
    case 'set index':
      return {...state, node: action.node, index: action.index};
    default:
      throw new Error('Invalid action');
  }
}

export function getRovingIndexActionFromEvent(
  event: React.KeyboardEvent
): RovingTabIndexUserActions | null {
  // @TODO it would be trivial to extend this and support
  // things like j/k vim-like navigation or add modifiers
  // so that users could jump to parent or sibling nodes.
  // I would need to put some thought into this, but shift+cmd+up
  // seems like a good candidate for jumping to parent node and
  // shift+cmd+down for jumping to the next sibling node.
  switch (event.key) {
    case 'ArrowDown':
      if (event.shiftKey) {
        return 'last';
      }
      return 'next';
    case 'ArrowUp':
      if (event.shiftKey) {
        return 'first';
      }
      return 'previous';
    case 'Home':
      return 'first';
    case 'End':
      return 'last';
    case 'Tab':
      if (event.shiftKey) {
        return 'previous';
      }
      return 'next';

    default:
      return null;
  }
}
