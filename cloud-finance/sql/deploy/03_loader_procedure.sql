-- Loader procedure. Requires CODE_STAGE/cloud_finance.zip (see SNOWFLAKE.md).
-- The handler wraps snowflake_backend.load_snapshot, the same loader the CLI uses.
USE ROLE CLOUDLEDGER_ROLE;
USE SCHEMA CLOUDLEDGER.CLOUD_FINANCE_BI;
CREATE OR REPLACE PROCEDURE LOAD_COST_EXPLORER_SNAPSHOT(PAYLOAD VARCHAR)
  RETURNS VARCHAR
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11'
  PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@CLOUDLEDGER.CLOUD_FINANCE_BI.CODE_STAGE/cloud_finance.zip')
  HANDLER = 'cloud_finance.snowpark_adapter.load_procedure'
  EXECUTE AS CALLER;
