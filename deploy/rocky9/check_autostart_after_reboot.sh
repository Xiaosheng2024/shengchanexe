#!/usr/bin/env bash
set -u

failed=0

check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "PASS: ${label}"
  else
    echo "FAIL: ${label}"
    failed=1
  fi
}

if systemctl list-unit-files postgresql-16.service >/dev/null 2>&1; then
  postgres_service="postgresql-16"
else
  postgres_service="postgresql"
fi

check "mes-web enabled" systemctl is-enabled --quiet mes-web
check "mes-web active" systemctl is-active --quiet mes-web
check "${postgres_service} enabled" systemctl is-enabled --quiet "${postgres_service}"
check "${postgres_service} active" systemctl is-active --quiet "${postgres_service}"

for _attempt in {1..10}; do
  listen_data="$(ss -lnt)"
  if grep -Eq '0\.0\.0\.0:8000|\*:8000' <<<"${listen_data}" \
    && curl --fail --silent --head --max-time 2 http://127.0.0.1:8000/ >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if grep -Eq '0\.0\.0\.0:8000|\*:8000' <<<"${listen_data}"; then
  echo "PASS: Web listens on all interfaces port 8000"
else
  echo "FAIL: Web is not listening on all interfaces port 8000"
  failed=1
fi

postgres_listeners="$(grep -E ':5432([[:space:]]|$)' <<<"${listen_data}" || true)"
unsafe_postgres_listeners="$(grep -Ev '127\.0\.0\.1:5432([[:space:]]|$)' <<<"${postgres_listeners}" || true)"
if grep -Eq '127\.0\.0\.1:5432([[:space:]]|$)' <<<"${postgres_listeners}" \
  && [[ -z "${unsafe_postgres_listeners}" ]]; then
  echo "PASS: PostgreSQL listens only on 127.0.0.1:5432"
else
  echo "FAIL: PostgreSQL listen address is unsafe or unavailable"
  failed=1
fi

check "local Web HTTP response" curl --fail --silent --head --max-time 5 http://127.0.0.1:8000/

if ((failed)); then
  echo "RESULT: FAIL"
  exit 1
fi

echo "RESULT: PASS"
