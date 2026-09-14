def get_user(user_id):
    user = db.get(user_id)
    return user


def create_user(name, email):
    return db.insert({"name": name, "email": email})
