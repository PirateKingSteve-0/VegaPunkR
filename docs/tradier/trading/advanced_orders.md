Advanced Orders

# Advanced Orders

# Getting Started with Advanced Orders

Advanced orders allow one to place a sequence of orders in a single request.  Typically, they rely on triggering conditions set with the market center that will take a particular action on the orders.

#### Advanced Order Types

* **One-triggers-other (OTO)** - if the first order is filled, the second order is placed.
* **One-cancels-other (OCO)** - if the first order is filled, the second order is canceled.
* **One-triggers-one-cancels-other (OTOCO)** - if the first order is filled, a one-cancels-other (OCO) is placed.

#### Requests

Sending multiple orders is similar to sending multiple legs in that each order's property keys are indexed (`symbol[2]`) to specify the correct arrangement of the orders.

#### Validations

Advanced orders have some different validations than regular orders.  Each order type, has some special validations that will be enforced on order placement.

**One-cancels-other (OCO)**

* `type` must be different for both legs.
* If both orders are equities, the `symbol` must be the same.
* If both orders are options, the `option_symbol` must be the same.
* If sending `duration` per leg, both orders must have the same duration.

**One-triggers-one-cancels-other (OTOCO)**

* If all equity orders, second and third orders must have the same `symbol`.
* If all option orders, second and third orders must have the same `option_symbol`.
* Second and third orders must always have a different type.
* If sending `duration` per leg, second and third orders must have the same duration.