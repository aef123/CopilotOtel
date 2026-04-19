@echo off
echo Starting Grafana Observability Stack...

if not exist "C:\logs\CopilotCli" mkdir "C:\logs\CopilotCli"

pushd "%~dp0"
docker compose up -d
popd

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Stack started successfully!
    echo.
    echo   Grafana:    http://localhost:3000
    echo   OTLP gRPC:  localhost:4317
    echo   OTLP HTTP:  localhost:4318
    echo   File output: C:\logs\CopilotCli\otel-telemetry.json
    echo.
    echo To stop: docker compose -f "%~dp0docker-compose.yaml" down
) else (
    echo Failed to start stack. Is Docker running?
)
