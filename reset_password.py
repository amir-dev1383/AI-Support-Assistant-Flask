from werkzeug.security import generate_password_hash # type: ignore

new_password = "12345678"

hashed = generate_password_hash(new_password)

print(hashed)
