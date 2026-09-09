export interface SQLQueryRequest {
  query: string;
  database?: string;
}

export interface SQLExecuteRequest {
  sql: string;
  database?: string;
}

export interface SQLQueryResponse {
  sql: string;
  explanation: string;
  results?: SQLResults;
  error?: string;
}

export interface SQLResults {
  columns: string[];
  rows: unknown[][];
  rowCount: number;
}

export interface SQLSchema {
  database: string;
  tables: SQLTable[];
}

export interface SQLTable {
  name: string;
  columns: SQLColumn[];
}

export interface SQLColumn {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
}

export interface SQLConnection {
  name: string;
  url: string;
}
