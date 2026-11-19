# MYCO's local PgBouncer: PgBouncer from the PostgreSQL project's own Debian repository (apt.postgresql.org), on the
# same official postgres image as myco-postgres, so it adds almost nothing to download. Pinned to an exact release:
# the build stops if the repository does not have it. 1.25.2 and later carry the May 2026 security fixes.
ARG POSTGRES_IMAGE=postgres:18.6
FROM ${POSTGRES_IMAGE}
ARG PGBOUNCER_VERSION=1.26.1
RUN set -eux; \
    apt-get update; \
    exact="$(apt-cache madison pgbouncer | awk -v want="${PGBOUNCER_VERSION}" '$3 ~ "^"want"-" {print $3; exit}')"; \
    test -n "$exact" || { echo "PgBouncer ${PGBOUNCER_VERSION} is not in apt.postgresql.org"; apt-cache madison pgbouncer; exit 1; }; \
    apt-get install -y --no-install-recommends "pgbouncer=${exact}"; \
    rm -rf /var/lib/apt/lists/*; \
    pgbouncer --version
COPY entrypoint.sh /usr/local/bin/myco-pgbouncer
USER postgres
ENTRYPOINT ["/usr/local/bin/myco-pgbouncer"]
