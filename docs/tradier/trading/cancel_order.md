Cancel Order

# Cancel Order

Cancel an existing order

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
    "/v1/accounts/{account_id}/orders/{order_id}": {
      "delete": {
        "tags": [
          "Trading"
        ],
        "summary": "Cancel Order",
        "description": "Cancel an existing order",
        "operationId": "brokerage-api-trading-cancel-order",
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
            "name": "order_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "integer"
            },
            "description": "ID of the order to cancel",
            "example": 123456
          }
        ],
        "responses": {
          "200": {
            "description": "Order cancellation response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "order": {
                      "type": "object",
                      "properties": {
                        "id": {
                          "type": "integer",
                          "description": "The order ID"
                        },
                        "status": {
                          "type": "string",
                          "enum": [
                            "ok",
                            "pending_cancel"
                          ],
                          "description": "The status of the cancellation"
                        }
                      }
                    }
                  }
                },
                "example": {
                  "order": {
                    "id": 123456,
                    "status": "ok"
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
    }
  }
}
```