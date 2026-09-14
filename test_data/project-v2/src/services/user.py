def get_user(user_id):
    user = db.get_user(user_id)
    if user is None:
        raise ValueError("user not found")
    return user


def create_user(name, email):
    return db.insert({"name": name, "email": email})
