#!/usr/bin/env python3
import json
import os
import tempfile
import time

import data


def write(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(value)


def main():
    with tempfile.TemporaryDirectory() as directory:
        now_path = os.path.join(directory, "now.json")
        history_path = os.path.join(directory, "history.jsonl")
        now = int(time.time())

        result = data.load(now_path, history_path, now)
        assert not result["available"] and result["history"] == []

        write(now_path, "")
        write(history_path, "")
        result = data.load(now_path, history_path, now)
        assert not result["available"] and result["today_cost"] == 0

        write(now_path, json.dumps({"rate_limits": None}))
        write(history_path, json.dumps({"ts": now, "session": "one", "cost": 1}) + "\n{" )
        result = data.load(now_path, history_path, now)
        assert result["rate_limits"]["five_hour"]["used_percentage"] == 0
        assert len(result["history"]) == 1

        rows = []
        for session, costs in (("one", (1, 2)), ("two", (0.5, 1.5)), ("three", (3, 4))):
            for cost in costs:
                rows.append({"ts": now, "session": session, "cost": cost})
        result = data.from_payload({}, rows, now)
        assert result["today_cost"] == 7.5, result["today_cost"]


if __name__ == "__main__":
    main()
