import json
import re
from datetime import datetime
from html import unescape

from app.models import Feedback
from tests.conftest import login, make_app, register


def post(client, rating, message):
    return client.post("/api/feedback", json={"rating": rating, "message": message})


def page_rows(client):
    html = client.get("/feedback").get_data(as_text=True)
    body = html[html.index('id="feedbackRows"'):html.index("</tbody>")]
    return [[unescape(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
            for tr in re.findall(r"<tr>(.*?)</tr>", body, flags=re.S)], html


def test_page_structure_and_order(client, user):
    html = client.get("/feedback").get_data(as_text=True)
    assert "Tell Us What You Think" in html and 'placeholder="Write your feedback here..."' in html
    assert ">Send Feedback</button>" in html and "<fieldset" in html
    radios = re.findall(r'<input type="radio" name="rating" id="rate\d" value="(\d)" required', html)
    assert radios == ["5", "4", "3", "2", "1"]  # five single-choice options, all required
    for n in range(1, 6):
        assert f"{'&#9733;' * n}</span> &ndash; {n}/5" in html  # real star symbols, not just numbers
    assert re.search(r'<textarea[^>]*required', html)
    assert html.index("Send Feedback</button>") < html.index("My Submitted Feedback") < html.index("<thead>")
    assert html.index("Rating") < html.index("Your Feedback")
    assert "You haven't submitted any feedback yet." in html
    assert 'id="feedbackTableWrap" hidden' in html  # the table stays hidden until there is feedback
    for col in ["Date &amp; Time", "Rating", "Feedback Message"]:
        assert f"<th>{col}</th>" in html
    assert "feedback.js" in html


def test_submit_saves_for_logged_in_user_and_returns_refreshed_list(client, user, db):
    r = post(client, 5, "Excellent quiz experience!")
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] and len(j["items"]) == 1
    row = db.query(Feedback).one()
    assert (row.user_id, row.rating, row.message) == (1, 5, "Excellent quiz experience!") and row.created_at is not None
    assert j["items"][0]["stars"] == "\u2605\u2605\u2605\u2605\u2605 (5/5)" and j["items"][0]["message"] == "Excellent quiz experience!"
    r2 = post(client, 4, "Good website.").get_json()
    assert [i["message"] for i in r2["items"]] == ["Good website.", "Excellent quiz experience!"]  # newest first
    assert [i["stars"] for i in r2["items"]] == ["\u2605\u2605\u2605\u2605 (4/5)", "\u2605\u2605\u2605\u2605\u2605 (5/5)"]


def test_table_shows_date_time_stars_and_full_message_newest_first(client, user, db):
    long_msg = "Line one of my feedback.\nLine two " + "x" * 300
    db.add_all([Feedback(user_id=1, rating=5, message="Excellent quiz experience!", created_at=datetime(2026, 11, 2, 5, 0)),
                Feedback(user_id=1, rating=4, message="Good website.", created_at=datetime(2026, 11, 1, 10, 45)),
                Feedback(user_id=1, rating=2, message=long_msg, created_at=datetime(2026, 10, 30, 9, 0))])
    db.commit()
    data, html = page_rows(client)
    assert data[0] == ["02 Nov 2026, 10:30 AM", "\u2605\u2605\u2605\u2605\u2605 (5/5)", "Excellent quiz experience!"]  # IST
    assert data[1] == ["01 Nov 2026, 04:15 PM", "\u2605\u2605\u2605\u2605 (4/5)", "Good website."]
    assert data[2][2] == long_msg and data[2][1] == "\u2605\u2605 (2/5)"  # the complete message
    assert "You haven't submitted any feedback yet." in html and 'id="feedbackEmpty" hidden' in html


def test_required_fields_validated_on_backend(client, user, db):
    bad = [(None, "text"), ("", "text"), (0, "text"), (6, "text"), ("abc", "text"), (3.5, "text"), (True, "text"),
           (5, ""), (5, "    "), (5, "\n\t  \n"), (5, None), (5, "x" * 2001)]
    for rating, message in bad:
        r = post(client, rating, message)
        assert r.status_code == 400 and r.get_json()["ok"] is False, (rating, message)
    assert post(client, 5, "x" * 2000).status_code == 200
    assert db.query(Feedback).count() == 1
    assert client.post("/api/feedback", data="not json", content_type="text/plain").status_code == 400
    assert "Please select a rating." in post(client, None, "ok").get_json()["error"]
    assert "Please write your feedback." in post(client, 5, "  ").get_json()["error"]


def test_message_is_trimmed_and_single_rating_only(client, user, db):
    post(client, "4", "   Nice quiz   ")
    f = db.query(Feedback).one()
    assert (f.rating, f.message) == (4, "Nice quiz")


def test_no_javascript_form_fallback(client, user, db):
    r = client.post("/feedback", data={"message": "Only text"})
    assert r.status_code == 400 and "Please select a rating." in r.get_data(as_text=True)
    r = client.post("/feedback", data={"rating": "3", "message": "   "})
    assert r.status_code == 400 and "Please write your feedback." in r.get_data(as_text=True)
    assert db.query(Feedback).count() == 0
    r = client.post("/feedback", data={"rating": "3", "message": "Works without JS"})
    assert r.status_code == 302
    data, _ = page_rows(client)
    assert data[0][2] == "Works without JS"


def test_only_own_feedback_is_visible_and_submission_needs_login(app, client, user):
    post(client, 5, "Alice's secret opinion")
    bob = app.test_client()
    register(bob, "bob")
    login(bob, "bob")
    post(bob, 1, "Bob's note")
    assert "Alice's secret opinion" not in bob.get("/feedback").get_data(as_text=True)
    assert "Bob's note" not in client.get("/feedback").get_data(as_text=True)
    assert [i["message"] for i in bob.get("/api/feedback").get_json()["items"]] == ["Bob's note"]
    assert [i["message"] for i in client.get("/api/feedback").get_json()["items"]] == ["Alice's secret opinion"]
    anon = app.test_client()
    assert anon.post("/api/feedback", json={"rating": 5, "message": "x"}).status_code == 401
    assert anon.get("/api/feedback").status_code == 401 and anon.get("/feedback").status_code == 302
    # a user id supplied by the browser is ignored: the saved row always belongs to the session user
    client.post("/api/feedback", json={"rating": 5, "message": "mine", "user_id": 2})
    from app.models import Feedback as F
    s = app.extensions["db_sessionmaker"]()
    assert s.query(F).filter_by(message="mine").one().user_id == 1


def test_feedback_survives_logout_login_and_restart(tmp_path):
    app1 = make_app(tmp_path)
    c1 = app1.test_client()
    register(c1)
    login(c1)
    post(c1, 5, "Persistent feedback")
    c1.post("/logout")
    login(c1)
    assert page_rows(c1)[0][0][2] == "Persistent feedback"
    app2 = make_app(tmp_path)  # simulated restart / redeploy
    c2 = app2.test_client()
    login(c2)
    assert page_rows(c2)[0][0][2] == "Persistent feedback"


def test_user_text_is_escaped(client, user):
    post(client, 3, "<script>alert(1)</script> & <b>bold</b>")
    html = client.get("/feedback").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert json.dumps(client.get("/api/feedback").get_json())  # JSON carries the raw text; the page JS uses textContent


def test_old_feedback_without_rating_still_displays(client, user, db):
    db.add(Feedback(user_id=1, rating=None, message="Old message from before ratings were required",
                    created_at=datetime(2026, 1, 1)))
    db.commit()
    data, _ = page_rows(client)
    assert data[0][1] == "No rating" and "Old message" in data[0][2]


def test_csrf_is_enforced_for_the_api(tmp_path):
    app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    c = app.test_client()

    def tok(path):
        return re.search(r'name="csrf_token" value="([^"]+)"', c.get(path).get_data(as_text=True)).group(1)
    c.post("/register", data=dict(full_name="Al Ice", email="a@x.com", username="alice", gender="Male",
                                  password="secret1", confirm_password="secret1", csrf_token=tok("/register")))
    c.post("/login", data=dict(identifier="alice", password="secret1", csrf_token=tok("/login")))
    assert c.post("/api/feedback", json={"rating": 5, "message": "x"}).status_code == 400  # no token
    meta = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/feedback").get_data(as_text=True)).group(1)
    assert c.post("/api/feedback", json={"rating": 5, "message": "ok"}, headers={"X-CSRFToken": meta}).status_code == 200


def test_save_failure_returns_safe_error(client, user, monkeypatch):
    from app.services import feedback as fb
    monkeypatch.setattr(fb, "create", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db password leaked")))
    r = post(client, 5, "will fail")
    assert r.status_code == 500 and "leaked" not in r.get_data(as_text=True)
    assert r.get_json()["error"] == "Could not send your feedback. Please try again."


def test_rate_limit_applies_to_feedback_api(tmp_path):
    app = make_app(tmp_path, RATELIMIT_ENABLED=True, FEEDBACK_RATE_LIMIT="2 per minute")
    c = app.test_client()
    register(c)
    login(c)
    codes = [post(c, 5, f"msg {i}").status_code for i in range(4)]
    assert codes == [200, 200, 429, 429]
