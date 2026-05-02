Get Account's Balances Overtime

# Get Account's Balances Overtime

Get the historical account balances to track value over time

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
    "/v1/accounts/{account_id}/historical-balances": {
      "get": {
        "tags": [
          "Accounts"
        ],
        "summary": "Get Account's Balances Overtime",
        "description": "Get the historical account balances to track value over time",
        "operationId": "brokerage-api-accounts-get-account-historical-balance",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/AccountIdParam"
          },
          {
            "$ref": "#/components/parameters/AcceptHeader"
          },
          {
            "name": "period",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "WEEK",
                "MONTH",
                "YTD",
                "YEAR",
                "YEAR_3",
                "YEAR_5",
                "ALL"
              ]
            },
            "description": "Type of activities to return"
          }
        ],
        "responses": {
          "200": {
            "description": "Account historical balance information",
            "content": {
              "application/json": {
                "schema": {},
                "example": {
                  "balances": [
                    {
                      "date": "2025-07-15",
                      "value": 113302.4
                    },
                    {
                      "date": "2025-07-16",
                      "value": 114357.75
                    },
                    {
                      "date": "2025-07-17",
                      "value": 115334.62
                    },
                    {
                      "date": "2025-07-18",
                      "value": 114963.65
                    },
                    {
                      "date": "2025-07-21",
                      "value": 116083.06
                    }
                  ],
                  "delta": 2780.66,
                  "deltaPercent": 2.45
                }
              }
            }
          },
          "401": {
            "$ref": "#/components/responses/Unauthorized"
          },
          "403": {
            "$ref": "#/components/responses/Forbidden"
          },
          "404": {
            "$ref": "#/components/responses/NotFound"
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
      },
      "AccountIdParam": {
        "name": "account_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string"
        },
        "description": "ID of the account",
        "example": "VA000001"
      }
    },
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
      },
      "Forbidden": {
        "description": "Access denied to the requested resource"
      },
      "NotFound": {
        "description": "The requested resource was not found"
      }
    },
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Bearer <access_token>",
        "description": "Authentication using Bearer token"
      }
    }
  }
}
```