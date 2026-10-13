-- Runs once, on first start of an empty data volume, inside the POSTGRES_DB database (sbi).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- Separate database for the MLflow backend store.
CREATE DATABASE mlflow;
