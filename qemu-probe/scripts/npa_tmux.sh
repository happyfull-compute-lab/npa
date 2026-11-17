#!/usr/bin/env bash
# NPA QEMU probe — tmux 4-pane consoles (root / hyp / linux / vmfw)
set -euo pipefail
SESSION=${SESSION:-npa-qemu}
ROOT=${ROOT:-/home/dev/git/npa/qemu-probe}

tmux new-session -d -s "$SESSION" -n npa -c "$ROOT"
tmux split-window -h -t "$SESSION"
tmux split-window -v -t "$SESSION:0.0"
tmux split-window -v -t "$SESSION:0.1"

tmux send-keys -t "$SESSION:0.0" 'echo "=== :0 root console ==="; clear' C-m
tmux send-keys -t "$SESSION:0.1" 'echo "=== :1 hyp console ==="; clear' C-m
tmux send-keys -t "$SESSION:0.2" 'echo "=== :2 linux console ==="; clear' C-m
tmux send-keys -t "$SESSION:0.3" 'echo "=== :3 vmfw console ==="; clear' C-m

tmux select-pane -t "$SESSION:0.0"
tmux attach -t "$SESSION"
