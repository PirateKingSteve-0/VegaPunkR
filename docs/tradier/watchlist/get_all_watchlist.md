Get All Watchlists

# Get All Watchlists

Retrieve all of a user's watchlists

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
    "/v1/watchlists": {
      "get": {
        "tags": [
          "Watchlists"
        ],
        "summary": "Get All Watchlists",
        "description": "Retrieve all of a user's watchlists",
        "operationId": "brokerage-api-watchlists-get-watchlists",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/AcceptHeader"
          }
        ],
        "responses": {
          "200": {
            "description": "List of user watchlists",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WatchlistsResponse"
                },
                "example": {
                  "watchlists": {
                    "watchlist": [
                      {
                        "name": "default",
                        "id": "default",
                        "public_id": "public-atea42pd"
                      },
                      {
                        "name": "a c d",
                        "id": "a-c-d",
                        "public_id": "public-5672lg0a"
                      }
                    ]
                  }
                }
              }
            }
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
      "WatchlistsResponse": {
        "type": "object",
        "properties": {
          "watchlists": {
            "type": "object",
            "properties": {
              "watchlist": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/WatchlistSummary"
                },
                "description": "List of watchlists"
              }
            }
          }
        }
      },
      "WatchlistSummary": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "The watchlist name"
          },
          "id": {
            "type": "string",
            "description": "The watchlist ID"
          },
          "public_id": {
            "type": "string",
            "description": "The public ID of the watchlist"
          }
        }
      }
    }
  }
}
```