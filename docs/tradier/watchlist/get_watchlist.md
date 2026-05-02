Get Specific Watchlist

# Get Specific Watchlist

Retrieve a specific watchlist by id

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
    "/v1/watchlists/{watchlist_id}": {
      "get": {
        "tags": [
          "Watchlists"
        ],
        "summary": "Get Specific Watchlist",
        "description": "Retrieve a specific watchlist by id",
        "operationId": "brokerage-api-watchlists-get-specific-watchlist",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "$ref": "#/components/parameters/WatchlistIdParam"
          },
          {
            "$ref": "#/components/parameters/AcceptHeader"
          }
        ],
        "responses": {
          "200": {
            "description": "Watchlist information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WatchlistResponse"
                },
                "example": {
                  "watchlist": {
                    "name": "default",
                    "id": "default",
                    "public_id": "public-atea42pd",
                    "items": {
                      "item": [
                        {
                          "symbol": "AAPL",
                          "id": "aapl"
                        },
                        {
                          "symbol": "AMZN",
                          "id": "amzn"
                        }
                      ]
                    }
                  }
                }
              }
            }
          },
          "401": {
            "$ref": "#/components/responses/Unauthorized"
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
      "WatchlistIdParam": {
        "name": "watchlist_id",
        "in": "path",
        "required": true,
        "schema": {
          "type": "string"
        },
        "description": "ID of the watchlist",
        "example": "my_watchlist"
      }
    },
    "responses": {
      "Unauthorized": {
        "description": "Authentication required or invalid credentials"
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
      "WatchlistResponse": {
        "type": "object",
        "properties": {
          "watchlist": {
            "$ref": "#/components/schemas/Watchlist"
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
      },
      "Watchlist": {
        "allOf": [
          {
            "$ref": "#/components/schemas/WatchlistSummary"
          },
          {
            "type": "object",
            "properties": {
              "items": {
                "type": "object",
                "properties": {
                  "item": {
                    "type": "array",
                    "items": {
                      "$ref": "#/components/schemas/WatchlistItem"
                    },
                    "description": "List of symbols in the watchlist"
                  }
                }
              }
            }
          }
        ]
      },
      "WatchlistItem": {
        "type": "object",
        "properties": {
          "symbol": {
            "type": "string",
            "description": "The security symbol"
          },
          "id": {
            "type": "string",
            "description": "The symbol ID (lowercase)"
          }
        }
      }
    }
  }
}
```