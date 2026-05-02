Get Account Gain/Loss

# Get Account Gain/Loss

Get cost basis and gain/loss information for an account. This includes information for all closed positions. Cost basis information is updated through a nightly batch reconciliation process with our clearing firm

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
    "/v1/accounts/{account_id}/gainloss": {
      "get": {
        "tags": [
          "Accounts"
        ],
        "summary": "Get Account Gain/Loss",
        "description": "Get cost basis and gain/loss information for an account. This includes information for all closed positions. Cost basis information is updated through a nightly batch reconciliation process with our clearing firm",
        "operationId": "brokerage-api-accounts-get-account-gainloss",
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
            "name": "page",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer",
              "default": 1
            },
            "description": "Page number for pagination"
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer",
              "default": 100
            },
            "description": "Set a max number of number of positions to return"
          },
          {
            "name": "sortBy",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "closeDate",
                "openDate"
              ],
              "default": "closeDate"
            },
            "description": "Sort the results by specified field"
          },
          {
            "name": "sort",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "asc",
                "desc"
              ],
              "default": "desc"
            },
            "description": "Sort direction (ascending/descending)"
          }
        ],
        "responses": {
          "200": {
            "description": "Account gain/loss information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GainLossResponse"
                },
                "example": {
                  "gainloss": {
                    "closed_position": [
                      {
                        "close_date": "2015-03-01T15:25:47.000Z",
                        "cost": 1450,
                        "gain_loss": 36.5,
                        "gain_loss_percent": 2.51,
                        "open_date": "2015-02-01T15:25:47.000Z",
                        "proceeds": 1486.5,
                        "quantity": 10,
                        "symbol": "AAPL",
                        "term": 28
                      }
                    ],
                    "page": 1,
                    "total_pages": 2,
                    "total_positions": 27
                  }
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
    },
    "schemas": {
      "ClosedPosition": {
        "type": "object",
        "properties": {
          "close_date": {
            "type": "string",
            "format": "date-time",
            "description": "The date the position was closed"
          },
          "cost": {
            "type": "number",
            "format": "float",
            "description": "The cost basis of the position"
          },
          "gain_loss": {
            "type": "number",
            "format": "float",
            "description": "The gain or loss amount"
          },
          "gain_loss_percent": {
            "type": "number",
            "format": "float",
            "description": "The gain or loss percentage"
          },
          "open_date": {
            "type": "string",
            "format": "date-time",
            "description": "The date the position was opened"
          },
          "proceeds": {
            "type": "number",
            "format": "float",
            "description": "The proceeds from the closed position"
          },
          "quantity": {
            "type": "number",
            "format": "float",
            "description": "The quantity of the security"
          },
          "symbol": {
            "type": "string",
            "description": "The security symbol"
          },
          "term": {
            "type": "integer",
            "description": "The holding period in days"
          }
        }
      },
      "GainLossResponse": {
        "type": "object",
        "properties": {
          "gainloss": {
            "type": "object",
            "properties": {
              "closed_position": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/ClosedPosition"
                },
                "description": "List of closed positions"
              },
              "page": {
                "type": "integer",
                "description": "Current page number"
              },
              "total_pages": {
                "type": "integer",
                "description": "Total number of pages"
              },
              "total_positions": {
                "type": "integer",
                "description": "Total number of positions"
              }
            }
          }
        }
      }
    }
  }
}
```