start a run

    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque", "pin":1234}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

skip the first part of a run
restart the kiln on a specific profile and start at minute 60

    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque","startat":60, "pin":1234}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

stop a schedule

    curl -d '{"cmd":"stop"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

errors

    If a request fails, the API returns:
    {"success": false, "error": "<reason>"}

    Common reasons include:
    - "invalid pin"
    - "kiln already running"
    - "profile <name> not found"
    - profile validation errors (e.g., out-of-range temperatures)

post a memo

    curl -d '{"cmd":"memo", "memo":"some significant message"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

stats for currently running schedule

    curl -X GET http://0.0.0.0:8081/api/stats

pause a run (maintain current temperature until resume)

    curl -d '{"cmd":"pause"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

resume a paused run
    
    curl -d '{"cmd":"resume"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
