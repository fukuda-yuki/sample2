FROM mcr.microsoft.com/dotnet/sdk:8.0.425-bookworm-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends python3 git curl ca-certificates iproute2 \
    && rm -rf /var/lib/apt/lists/*
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 NUGET_PACKAGES=/opt/nuget-cache
RUN mkdir /seed && cd /seed && dotnet new web --framework net8.0 \
    && dotnet add package Microsoft.EntityFrameworkCore.Sqlite --version 8.0.31 \
    && dotnet add package Microsoft.Data.Sqlite --version 8.0.31 \
    && rm -rf /seed && chmod -R a+rX /opt/nuget-cache

FROM base AS worker
ARG OPENCODE_VERSION=1.17.11
RUN curl -fsSL https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-x64.tar.gz \
    | tar -xz -C /usr/local/bin && opencode --version
ENV HOME=/tmp/home XDG_CONFIG_HOME=/tmp/config XDG_DATA_HOME=/state XDG_CACHE_HOME=/tmp/cache \
    OPENCODE_DISABLE_AUTOUPDATE=true OPENCODE_DISABLE_MODELS_FETCH=true \
    OPENCODE_DISABLE_DEFAULT_PLUGINS=true
WORKDIR /workspace
USER 1000:1000

FROM base AS evaluator-build
WORKDIR /build
COPY inner/evaluator/ /build/
ARG EVALUATOR_PROJECT=MusicStore.Evaluator/MusicStore.Evaluator.csproj
RUN dotnet publish "$EVALUATOR_PROJECT" -c Release -o /evaluator --nologo

FROM base AS evaluator
COPY --from=evaluator-build /evaluator /evaluator
ENV HOME=/tmp/home XDG_DATA_HOME=/tmp/data XDG_CONFIG_HOME=/tmp/config
WORKDIR /work
USER 1000:1000

FROM python:3.12-slim-bookworm AS gateway
COPY outer/harness/gateway.py /app/gateway.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["python3", "/app/gateway.py"]
