"""Login-change plan: password generation + Argon2id hashing."""

from app.core.password_utils import generate_password, hash_password, verify_password


def test_generate_password_default_length():
    pw = generate_password()
    assert len(pw) == 16


def test_generate_password_custom_length():
    pw = generate_password(length=24)
    assert len(pw) == 24


def test_generate_password_excludes_ambiguous_characters():
    ambiguous = set("0O1lI")
    for _ in range(20):
        pw = generate_password(length=32)
        assert not (set(pw) & ambiguous)


def test_generate_password_is_random_across_calls():
    passwords = {generate_password() for _ in range(20)}
    assert len(passwords) == 20  # vanishingly unlikely to collide


def test_hash_password_produces_a_verifiable_hash():
    pw = "correct-horse-battery-staple"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("the-real-password")
    assert verify_password("not-the-real-password", hashed) is False


def test_verify_password_rejects_malformed_hash():
    assert verify_password("anything", "not-a-real-argon2-hash") is False


def test_hash_password_is_salted_differently_each_time():
    pw = "same-password-twice"
    assert hash_password(pw) != hash_password(pw)
