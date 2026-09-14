def charge(amount, currency="USD"):
    if amount <= 0:
        raise ValueError("amount must be positive")
    return {"status": "charged", "amount": amount, "currency": currency}
