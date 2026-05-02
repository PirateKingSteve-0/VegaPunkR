Remove Symbol from Watchlist

# Remove Symbol from Watchlist

Remove a symbol from a specific watchlist

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
    "/v1/watchlists/{watchlist_id}/symbols/{symbol}": {
      "delete": {
        "tags": [
          "Watchlists"
        ],
        "summary": "Remove Symbol from Watchlist",
        "description": "Remove a symbol from a specific watchlist",
        "operationId": "brokerage-api-watchlists-remove-watchlist-symbol",
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
            "name": "symbol",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "description": "Symbol to remove from watchlist",
            "example": "SPY"
          },
          {
            "$ref": "#/components/parameters/AcceptHeader"
          }
        ],
        "responses": {
          "200": {
            "description": "Symbol removed successfully",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WatchlistResponse"
                },
                "example": {
                  "watchlist": {
                    "name": "My Watchlist",
                    "id": "my_watchlist",
                    "public_id": "public-6f8f625wti",
                    "items": {
                      "item": [
                        {
                          "symbol": "AAPL",
                          "id": "aapl"
                        },
                        {
                          "symbol": "IBM",
                          "id": "ibm"
                        },
                        {
                          "symbol": "NFLX",
                          "id": "nflx"
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