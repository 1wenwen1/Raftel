#!/bin/bash

# Get the current list of all tmux sessions
sessions=$(tmux list-sessions -F "#S")

# Loop through each session and close them.
for session in $sessions
do
    tmux kill-session -t "$session"
done