-- Deployment template, not executed against a Snowflake account.
-- Operate in a dedicated database/schema selected by the operator.
CREATE TABLE IF NOT EXISTS COST_DAILY (
  USAGE_DATE DATE NOT NULL,
  ACCOUNT_KEY VARCHAR NOT NULL,
  SERVICE VARCHAR NOT NULL,
  TEAM VARCHAR NOT NULL,
  UNBLENDED_COST NUMBER(28,10) NOT NULL,
  CURRENCY VARCHAR NOT NULL,
  ESTIMATED BOOLEAN NOT NULL,
  SOURCE_SNAPSHOT VARCHAR NOT NULL
);
-- Enforce (usage_date, account_key, service) uniqueness in ingestion tests.
-- Snowflake standard-table uniqueness constraints do not enforce the grain.
CREATE OR REPLACE VIEW MONTHLY_SERVICE_TEAM_COST AS
SELECT DATE_TRUNC('MONTH', USAGE_DATE) AS USAGE_MONTH, SERVICE, TEAM, CURRENCY,
       SUM(UNBLENDED_COST) AS ACTUAL_COST, BOOLOR_AGG(ESTIMATED) AS HAS_ESTIMATES
FROM COST_DAILY
GROUP BY 1,2,3,4;

-- Validation queries must return zero rows before publishing a snapshot.
SELECT USAGE_DATE, ACCOUNT_KEY, SERVICE, COUNT(*) AS ROW_COUNT
FROM COST_DAILY GROUP BY 1,2,3 HAVING COUNT(*) > 1;
SELECT * FROM COST_DAILY WHERE CURRENCY <> 'USD' OR TEAM IS NULL;
