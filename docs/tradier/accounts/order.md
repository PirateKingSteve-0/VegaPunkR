Get Account Orders

# Get Account Orders

Get current market session orders for an account.

This is the end point to get all orders for the current market session. A single call to this endpoint can retrieve up to 1500 orders. If you have more than 1500 orders for the current market session you can utilize pagination and filtering. If you have a single order, it will be returned as a JSON obj/dict whereas multiple orders will be returned as an array/list of JSON objects.

<br />

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
    "/v1/accounts/{account_id}/orders": {
      "get": {
        "tags": [
          "Accounts"
        ],
        "summary": "Get Account Orders",
        "description": "Get current market session orders for an account.",
        "operationId": "brokerage-api-accounts-get-account-orders",
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
            "name": "status",
            "in": "query",
            "required": false,
            "schema": {
              "type": "string",
              "default": null
            },
            "description": "A sing or list of order statuses to be filtered for. Can be one or more of: pending,open,partially_filled,filled,rejected,expired,canceled"
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer",
              "default": 25
            },
            "description": "Maximum number of order to be returned, 25 is defualt but you can set a high number such as 1000 to retrieve all your orders from this market session in one call"
          },
          {
            "name": "page",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer",
              "default": 1
            },
            "description": "Page number for pagination which is only useful for very large numbers of order broken into pages for faster retrieval"
          },
          {
            "name": "includeTags",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false
            },
            "description": "Include user-defined tags in response"
          }
        ],
        "responses": {
          "200": {
            "description": "Account orders information",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/OrdersResponse"
                },
                "example": {
                  "orders": {
                    "order": [
                      {
                        "id": 123456,
                        "type": "market",
                        "symbol": "AAPL",
                        "side": "buy",
                        "quantity": 10,
                        "status": "filled",
                        "duration": "day",
                        "avg_fill_price": 128.25,
                        "exec_quantity": 10,
                        "create_date": "2015-04-01T15:25:47.000Z",
                        "transaction_date": "2015-04-01T15:25:47.000Z",
                        "class": "equity"
                      },
                      {
                        "id": 228749,
                        "type": "market",
                        "symbol": "SPY",
                        "side": "buy_to_open",
                        "quantity": 1,
                        "status": "expired",
                        "duration": "pre",
                        "avg_fill_price": 0,
                        "exec_quantity": 0,
                        "last_fill_price": 0,
                        "last_fill_quantity": 0,
                        "remaining_quantity": 0,
                        "create_date": "2018-06-06T20:16:17.342Z",
                        "transaction_date": "2018-06-06T20:16:17.357Z",
                        "class": "option",
                        "option_symbol": "SPY180720C00274000"
                      },
                      {
                        "id": 229063,
                        "type": "debit",
                        "symbol": "SPY",
                        "side": "buy",
                        "quantity": 1,
                        "status": "canceled",
                        "duration": "pre",
                        "price": 42,
                        "avg_fill_price": 0,
                        "exec_quantity": 0,
                        "last_fill_price": 0,
                        "last_fill_quantity": 0,
                        "remaining_quantity": 0,
                        "create_date": "2018-06-12T21:13:36.076Z",
                        "transaction_date": "2018-06-12T21:18:41.604Z",
                        "class": "combo",
                        "num_legs": 2,
                        "strategy": "covered call",
                        "leg": [
                          {
                            "id": 229064,
                            "type": "debit",
                            "symbol": "SPY",
                            "side": "buy",
                            "quantity": 100,
                            "status": "canceled",
                            "duration": "pre",
                            "price": 42,
                            "avg_fill_price": 0,
                            "exec_quantity": 0,
                            "last_fill_price": 0,
                            "last_fill_quantity": 0,
                            "remaining_quantity": 0,
                            "create_date": "2018-06-12T21:13:36.076Z",
                            "transaction_date": "2018-06-12T21:18:41.587Z",
                            "class": "equity"
                          },
                          {
                            "id": 229065,
                            "type": "debit",
                            "symbol": "SPY",
                            "side": "sell_to_close",
                            "quantity": 1,
                            "status": "canceled",
                            "duration": "pre",
                            "price": 42,
                            "avg_fill_price": 0,
                            "exec_quantity": 0,
                            "last_fill_price": 0,
                            "last_fill_quantity": 0,
                            "remaining_quantity": 0,
                            "create_date": "2018-06-12T21:13:36.076Z",
                            "transaction_date": "2018-06-12T21:18:41.597Z",
                            "class": "option",
                            "option_symbol": "SPY180720C00274000"
                          }
                        ]
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
      "Order": {
        "type": "object",
        "properties": {
          "id": {
            "type": "integer",
            "description": "The order ID"
          },
          "type": {
            "type": "string",
            "description": "The order type",
            "enum": [
              "market",
              "limit",
              "stop",
              "stop_limit",
              "debit",
              "credit",
              "even"
            ]
          },
          "symbol": {
            "type": "string",
            "description": "The security symbol"
          },
          "side": {
            "type": "string",
            "description": "The side of the order",
            "enum": [
              "buy",
              "buy_to_cover",
              "sell",
              "sell_short",
              "buy_to_open",
              "buy_to_close",
              "sell_to_open",
              "sell_to_close"
            ]
          },
          "quantity": {
            "type": "number",
            "format": "float",
            "description": "The order quantity"
          },
          "status": {
            "type": "string",
            "description": "The order status",
            "enum": [
              "pending",
              "open",
              "partially_filled",
              "filled",
              "expired",
              "canceled",
              "rejected",
              "pending_cancel"
            ]
          },
          "duration": {
            "type": "string",
            "description": "The order duration",
            "enum": [
              "day",
              "gtc",
              "pre",
              "post"
            ]
          },
          "avg_fill_price": {
            "type": "number",
            "format": "float",
            "description": "The average fill price"
          },
          "exec_quantity": {
            "type": "number",
            "format": "float",
            "description": "The executed quantity"
          },
          "create_date": {
            "type": "string",
            "format": "date-time",
            "description": "The date the order was created"
          },
          "transaction_date": {
            "type": "string",
            "format": "date-time",
            "description": "The date of the last transaction"
          },
          "class": {
            "type": "string",
            "description": "The security class",
            "enum": [
              "equity",
              "option",
              "multileg",
              "combo"
            ]
          }
        }
      },
      "OrdersResponse": {
        "type": "object",
        "properties": {
          "orders": {
            "type": "object",
            "properties": {
              "order": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Order"
                },
                "description": "List of orders"
              },
              "page": {
                "type": "integer",
                "description": "Current page number"
              },
              "total_pages": {
                "type": "integer",
                "description": "Total number of pages"
              },
              "total_orders": {
                "type": "integer",
                "description": "Total number of orders"
              }
            }
          }
        }
      }
    }
  }
}
```