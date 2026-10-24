-- Streamlit in Snowflake app. Requires CODE_STAGE/app/ (snowflake_app.py,
-- environment.yml, cloud_finance/{__init__,data,analytics,workflow,snowflake_backend}.py).
USE ROLE CLOUDLEDGER_ROLE;
USE SCHEMA CLOUDLEDGER.CLOUD_FINANCE_BI;
CREATE OR REPLACE STREAMLIT CLOUDLEDGER_APP
  FROM '@CLOUDLEDGER.CLOUD_FINANCE_BI.CODE_STAGE/app'
  MAIN_FILE = 'snowflake_app.py'
  QUERY_WAREHOUSE = CLOUDLEDGER_WH
  TITLE = 'CloudLedger'
  COMMENT = 'Cloud spend trend, drivers, anomalies, forecast evaluation, AI review, QBR';
GRANT USAGE ON STREAMLIT CLOUDLEDGER_APP TO ROLE CLOUDLEDGER_VIEWER;
