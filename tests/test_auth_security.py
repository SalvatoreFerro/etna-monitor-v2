from app.utils.auth import hash_password, check_password

def test_password_hashing_roundtrip():
    h = hash_password("secret")
    assert h != "secret"
    assert check_password("secret", h) is True
    assert check_password("wrong", h) is False
