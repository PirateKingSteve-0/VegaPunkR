Get Account History

# Get Account History

Get historical activity for an account

<br />

This data originates with our clearing firm and inherently has a few limitations:

* Updated nightly (not intraday)
* Will not include specific time (hours/minutes) a position or order was created or closed
* Will not include order numbers
* Only available for live accounts (sandbox history not available)

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
    "/v1/accounts/{account_id}/history": {
      "get": {
        "tags": [
          "Accounts"
        ],
        "summary": "Get Account History",
        "description": "Get historical activity for an account",
        "operationId": "brokerage-api-accounts-get-account-history",
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
              "default": 25
            },
            "description": "Number of events to return"
          },
          {
            "name": "type",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "enum": [
                "trade",
                "option",
                "ach",
                "wire",
                "dividend",
                "fee",
                "tax",
                "journal",
                "check",
                "transfer",
                "adjustment"
              ]
            },
            "description": "Type of activities to return"
          }
        ],
        "responses": {
          "200": {
            "description": "Account history information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HistoryResponse"
                },
                "example": {
                  "history": {
                    "event": [
                      {
                        "date": "2015-04-01T15:25:47.000Z",
                        "type": "trade",
                        "symbol": "AAPL",
                        "quantity": 10,
                        "price": 124,
                        "amount": 1240,
                        "description": "Bought 10 AAPL @ 124.00",
                        "commission": 0
                      }
                    ]
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
      "HistoryEvent": {
        "type": "object",
        "properties": {
          "date": {
            "type": "string",
            "format": "date-time",
            "description": "The date of the event"
          },
          "type": {
            "type": "string",
            "description": "The type of event",
            "enum": [
              "trade",
              "option",
              "ach",
              "wire",
              "dividend",
              "fee",
              "tax",
              "journal",
              "check",
              "transfer",
              "adjustment"
            ]
          },
          "symbol": {
            "type": "string",
            "description": "The security symbol (for applicable event types)"
          },
          "quantity": {
            "type": "number",
            "format": "float",
            "description": "The quantity involved in the event (for applicable event types)"
          },
          "price": {
            "type": "number",
            "format": "float",
            "description": "The price per share/contract (for applicable event types)"
          },
          "amount": {
            "type": "number",
            "format": "float",
            "description": "The total amount of the event"
          },
          "description": {
            "type": "string",
            "description": "Description of the event"
          },
          "commission": {
            "type": "number",
            "format": "float",
            "description": "Commission charged for the event (for applicable event types)"
          }
        }
      },
      "HistoryResponse": {
        "type": "object",
        "properties": {
          "history": {
            "type": "object",
            "properties": {
              "event": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/HistoryEvent"
                },
                "description": "List of historical events"
              },
              "page": {
                "type": "integer",
                "description": "Current page number"
              },
              "total_pages": {
                "type": "integer",
                "description": "Total number of pages"
              },
              "total_events": {
                "type": "integer",
                "description": "Total number of events"
              }
            }
          }
        }
      }
    }
  }
}
```