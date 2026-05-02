Get historical pricing for a security.

# Get historical pricing for a security.

Get historical pricing for a specific security. This data will usually cover the entire lifetime of the company if sending reasonable start/end times. You can fetch historical pricing for options by passing the OCC option symbol (ex. AAPL220617C00270000) as the symbol.

<br />

This data will usually cover the entire lifetime of the company if sending reasonable start/end times. You can fetch historical pricing for options by passing the OCC option symbol (ex., AAPL220617C00270000) as the symbol.

# OpenAPI definition

```json
{
  "openapi": "3.0.0",
  "info": {
    "title": "Tradier Brokerage API",
    "description": "API for accessing Tradier brokerage services",
    "version": "1.0.0"
  },
  "servers": [
    {
      "url": "https://api.tradier.com",
      "description": "Production server"
    },
    {
      "url": "https://sandbox.tradier.com",
      "description": "Sandbox environment for testing"
    }
  ],
  "paths": {
    "/v1/markets/history": {
      "get": {
        "tags": [
          "Markets"
        ],
        "summary": "Get historical pricing for a security.",
        "description": "Get historical pricing for a specific security. This data will usually cover the entire lifetime of the company if sending reasonable start/end times. You can fetch historical pricing for options by passing the OCC option symbol (ex. AAPL220617C00270000) as the symbol.",
        "operationId": "brokerage-api-markets-get-history",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/AcceptHeader"
          },
          {
            "name": "symbol",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "The security symbol",
            "example": "AAPL"
          },
          {
            "name": "interval",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "daily",
                "weekly",
                "monthly"
              ],
              "default": "daily"
            },
            "description": "The interval for the data"
          },
          {
            "name": "start",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "format": "date"
            },
            "description": "The start date for the data (YYYY-MM-DD)",
            "example": "2020-01-01"
          },
          {
            "name": "end",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "format": "date"
            },
            "description": "The end date for the data (YYYY-MM-DD)",
            "example": "2021-01-01"
          }
        ],
        "responses": {
          "200": {
            "description": "Historical pricing data",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/MarketHistoryResponse"
                },
                "example": {
                  "history": {
                    "day": [
                      {
                        "date": "2020-01-02",
                        "open": 76.84,
                        "high": 77.15,
                        "low": 76.19,
                        "close": 77.05,
                        "volume": 53852941
                      },
                      {
                        "date": "2020-01-03",
                        "open": 76.17,
                        "high": 76.62,
                        "low": 75.56,
                        "close": 76.08,
                        "volume": 55385580
                      }
                    ],
                    "symbol": "AAPL"
                  }
                }
              }
            }
          },
          "400": {
            "$ref": "#/components/responses/BadRequest"
          },
          "401": {
            "$ref": "#/components/responses/Unauthorized"
          }
        }
      }
    }
  },
  "components": {
    "parameters": {
      "AcceptHeader": {
        "name": "Accept",
        "in": "header",
        "required": true,
        "schema": {
          "type": "string",
          "enum": [
            "application/json"
          ]
        },
        "description": "Response format"
      }
    },
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
      },
      "BadRequest": {
        "description": "Invalid request parameters or body"
      }
    },
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Bearer <access_token>",
        "description": "Authentication using Bearer token"
      }
    },
    "schemas": {
      "MarketHistoryResponse": {
        "type": "object",
        "properties": {
          "history": {
            "type": "object",
            "properties": {
              "day": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "date": {
                      "type": "string",
                      "format": "date",
                      "description": "The date"
                    },
                    "open": {
                      "type": "number",
                      "format": "float",
                      "description": "The opening price"
                    },
                    "high": {
                      "type": "number",
                      "format": "float",
                      "description": "The high price"
                    },
                    "low": {
                      "type": "number",
                      "format": "float",
                      "description": "The low price"
                    },
                    "close": {
                      "type": "number",
                      "format": "float",
                      "description": "The closing price"
                    },
                    "volume": {
                      "type": "integer",
                      "description": "The trading volume"
                    }
                  }
                }
              },
              "symbol": {
                "type": "string",
                "description": "The security symbol"
              }
            }
          }
        }
      }
    }
  }
}
```