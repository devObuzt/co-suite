import pytest

from api.models.user import User
from api.services.manzuma_accounts import ManzumaOrg, ManzumaSession, ManzumaSub
from api.services.manzuma_link import resolve_user


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeDB:
    """Answers by the column the query filters on, and remembers what was asked.

    Answering by order made the tests blind: with the email lookup deleted, the
    phone lookup consumed the email's answer and every assertion still passed.
    """

    COLUMNS = ("manzuma_user_id", "email", "phone")

    def __init__(self, by_column):
        self.by_column = by_column
        self.asked = []
        self.added = []
        self.commits = 0

    async def execute(self, statement, *_args, **_kwargs):
        sql = str(statement)
        column = next((c for c in self.COLUMNS if f"users.{c} = " in sql), None)
        assert column, f"unexpected query: {sql[:120]}"
        self.asked.append(column)
        return _Result(self.by_column.get(column))

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


SESSION = ManzumaSession(
    user_id="u1", email="W@Example.com", phone="050-123-4567", name="Wisam", organizations=()
)
ORG = ManzumaOrg(
    id="o1", name="Afkar", role="owner",
    subscriptions=(ManzumaSub(module="cosuite", plan="pro", status="active"),),
)


@pytest.mark.asyncio
async def test_returns_the_already_linked_user_without_writing():
    linked = User(id="local1", email="w@example.com", hashed_password="x", full_name="Wisam")
    linked.manzuma_user_id = "u1"
    db = FakeDB({"manzuma_user_id": linked})

    user = await resolve_user(db, SESSION, ORG)

    assert user is linked
    assert db.asked == ["manzuma_user_id"]  # no email or phone lookup
    assert db.added == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_adopts_a_legacy_user_by_email_and_keeps_its_status():
    legacy = User(id="local2", email="w@example.com", hashed_password="x", full_name="Wisam")
    legacy.approval_status = "frozen"
    db = FakeDB({"email": legacy})

    user = await resolve_user(db, SESSION, ORG)

    assert user is legacy
    assert user.manzuma_user_id == "u1"
    assert user.approval_status == "frozen"  # adoption never promotes
    assert db.asked == ["manzuma_user_id", "email"]  # the phone was never asked
    assert db.commits == 1
    assert db.added == []


@pytest.mark.asyncio
async def test_adopts_by_phone_when_the_email_does_not_match():
    legacy = User(id="local3", email="other@example.com", hashed_password="x", full_name="Wisam")
    db = FakeDB({"phone": legacy})

    user = await resolve_user(db, SESSION, ORG)

    assert user is legacy
    assert user.manzuma_user_id == "u1"
    assert db.asked == ["manzuma_user_id", "email", "phone"]


@pytest.mark.asyncio
async def test_creates_an_approved_user_when_the_business_pays_for_cosuite():
    db = FakeDB({})

    user = await resolve_user(db, SESSION, ORG)

    assert user.manzuma_user_id == "u1"
    assert user.email == "w@example.com"
    assert user.approval_status == "approved"
    assert user.hashed_password == ""  # no usable password
    assert db.added == [user]


@pytest.mark.asyncio
async def test_a_new_user_without_a_cosuite_subscription_stays_frozen():
    db = FakeDB({})
    no_sub = ManzumaOrg(id="o9", name="Nope", role="owner", subscriptions=())

    user = await resolve_user(db, SESSION, no_sub)

    assert user.approval_status == "frozen"
