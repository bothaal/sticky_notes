"""Behavioral tests for the documented sticky-notes workflows."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import NoteForm
from .models import Note


class NoteModelTests(TestCase):
    """Check note persistence, timestamps, ordering, and ownership."""

    @classmethod
    def setUpTestData(cls):
        """Create the shared owner for model tests."""
        cls.owner = get_user_model().objects.create_user(username="owner")

    def test_note_stores_its_fields_and_uses_title_as_string(self):
        """Persist note data and expose its title and owner relation."""
        note = Note.objects.create(
            owner=self.owner, title="Shopping", content="Milk\nBread"
        )
        note.refresh_from_db()
        self.assertEqual(note.title, "Shopping")
        self.assertEqual(note.content, "Milk\nBread")
        self.assertEqual(note.owner, self.owner)
        self.assertEqual(str(note), "Shopping")
        self.assertQuerySetEqual(self.owner.notes.all(), [note])

    def test_creation_sets_both_timestamps(self):
        """Set creation and modification timestamps when saving a new note."""
        created = timezone.now()
        with patch("django.utils.timezone.now", return_value=created):
            note = Note.objects.create(
                owner=self.owner, title="Title", content="Content"
            )
        note.refresh_from_db()
        self.assertEqual(note.created_at, created)
        self.assertEqual(note.updated_at, created)

    def test_save_updates_modified_time_but_preserves_creation_time(self):
        """Advance the update timestamp without changing creation time."""
        note = Note.objects.create(
            owner=self.owner, title="Title", content="Content"
        )
        created = note.created_at
        modified = note.updated_at + timedelta(days=1)
        with patch("django.utils.timezone.now", return_value=modified):
            note.content = "Changed"
            note.save()
        note.refresh_from_db()
        self.assertEqual(note.created_at, created)
        self.assertEqual(note.updated_at, modified)

    def test_notes_are_ordered_by_latest_update_not_creation(self):
        """Place an older note first when it has the most recent update."""
        first = Note.objects.create(
            owner=self.owner, title="First", content="Content"
        )
        second = Note.objects.create(
            owner=self.owner, title="Second", content="Content"
        )
        later = timezone.now() + timedelta(days=1)
        Note.objects.filter(pk=first.pk).update(updated_at=later)
        self.assertQuerySetEqual(Note.objects.all(), [first, second])

    def test_deleting_owner_deletes_only_their_notes(self):
        """Cascade owner deletion to their notes while preserving others."""
        other = get_user_model().objects.create_user(username="other")
        owned = Note.objects.create(
            owner=self.owner, title="Owned", content="Content"
        )
        unrelated = Note.objects.create(
            owner=other, title="Unrelated", content="Content"
        )
        self.owner.delete()
        self.assertFalse(Note.objects.filter(pk=owned.pk).exists())
        self.assertTrue(Note.objects.filter(pk=unrelated.pk).exists())


class NoteFormTests(TestCase):
    """Check editable fields and the documented title-length boundary."""

    def test_only_title_and_content_are_editable(self):
        """Expose only title and content fields in the note form."""
        self.assertEqual(list(NoteForm().fields), ["title", "content"])

    def test_valid_data_and_multiline_content_are_accepted(self):
        """Accept valid note data without removing content line breaks."""
        form = NoteForm(data={"title": "Reminder", "content": "One\nTwo"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["content"], "One\nTwo")

    def test_title_of_100_characters_is_valid(self):
        """Accept a title exactly at the 100-character limit."""
        form = NoteForm(data={"title": "T" * 100, "content": "Content"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_title_of_101_characters_is_rejected(self):
        """Reject a title one character beyond the allowed limit."""
        form = NoteForm(data={"title": "T" * 101, "content": "Content"})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["title"][0].code, "max_length")

    def test_missing_empty_and_whitespace_only_fields_are_rejected(self):
        """Require both fields to contain non-whitespace text."""
        for field in ("title", "content"):
            for value in (None, "", " \t\n "):
                with self.subTest(field=field, value=value):
                    data = {"title": "Title", "content": "Content"}
                    if value is None:
                        data.pop(field)
                    else:
                        data[field] = value
                    form = NoteForm(data=data)
                    self.assertFalse(form.is_valid())
                    self.assertEqual(
                        form.errors.as_data()[field][0].code, "required"
                    )


class NoteViewTests(TestCase):
    """Exercise CRUD, privacy, and invalid requests through real URLs."""

    @classmethod
    def setUpTestData(cls):
        """Create two users with separate notes for ownership checks."""
        cls.owner = get_user_model().objects.create_user(username="owner")
        cls.other = get_user_model().objects.create_user(username="other")
        cls.note = Note.objects.create(
            owner=cls.owner, title="Owner title", content="Owner content"
        )
        cls.other_note = Note.objects.create(
            owner=cls.other, title="Private title", content="Private content"
        )

    def setUp(self):
        """Authenticate the note owner before each view test."""
        self.client.force_login(self.owner)

    def assert_original_note_unchanged(self):
        """Check all persisted fields, including owner and timestamps."""
        current = Note.objects.get(pk=self.note.pk)
        for field in Note._meta.concrete_fields:
            self.assertEqual(
                getattr(current, field.attname),
                getattr(self.note, field.attname),
                field.name,
            )

    def test_list_renders_only_current_users_notes(self):
        """Display owned notes without exposing another user's note data."""
        response = self.client.get(reverse("note_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notes/note_list.html")
        self.assertQuerySetEqual(response.context["notes"], [self.note])
        self.assertContains(response, self.note.title)
        self.assertContains(response, self.note.content)
        self.assertNotContains(response, self.other_note.title)
        self.assertNotContains(response, self.other_note.content)

    def test_list_uses_latest_update_order(self):
        """List the current user's most recently updated note first."""
        newer = Note.objects.create(
            owner=self.owner, title="Newer", content="Content"
        )
        later = timezone.now() + timedelta(days=1)
        Note.objects.filter(pk=self.note.pk).update(updated_at=later)
        response = self.client.get(reverse("note_list"))
        self.assertQuerySetEqual(response.context["notes"], [self.note, newer])

    def test_user_without_notes_sees_empty_state(self):
        """Display the empty-state message when the user has no notes."""
        user = get_user_model().objects.create_user(username="empty")
        self.client.force_login(user)
        response = self.client.get(reverse("note_list"))
        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(response.context["notes"], [])
        self.assertContains(response, "You have no notes yet.")

    def test_detail_renders_owned_note(self):
        """Render the requested owned note using the detail template."""
        response = self.client.get(reverse("note_detail", args=[self.note.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notes/note_detail.html")
        self.assertEqual(response.context["note"], self.note)
        self.assertContains(response, self.note.title)
        self.assertContains(response, self.note.content)

    def test_create_get_displays_empty_form_without_saving(self):
        """Show an unbound creation form without inserting a note."""
        response = self.client.get(reverse("note_create"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notes/note_form.html")
        self.assertIsInstance(response.context["form"], NoteForm)
        self.assertFalse(response.context["form"].is_bound)
        self.assertIsNone(response.context["form"].instance.pk)
        self.assertEqual(Note.objects.count(), 2)

    def test_create_saves_data_and_ignores_forged_owner_and_timestamps(self):
        """Save valid data with server-controlled ownership and timestamps."""
        response = self.client.post(
            reverse("note_create"),
            {
                "title": "Created",
                "content": "First line\nSecond line",
                "owner": self.other.pk,
                "created_at": "2000-01-01T00:00:00Z",
                "updated_at": "2000-01-01T00:00:00Z",
            },
        )
        self.assertRedirects(response, reverse("note_list"))
        self.assertEqual(Note.objects.count(), 3)
        note = Note.objects.get(title="Created")
        self.assertEqual(note.content, "First line\nSecond line")
        self.assertEqual(note.owner, self.owner)
        self.assertNotEqual(note.created_at.year, 2000)
        self.assertNotEqual(note.updated_at.year, 2000)

    def test_invalid_create_displays_errors_and_saves_nothing(self):
        """Render validation errors without saving an invalid new note."""
        cases = [
            ({"content": "Content"}, "title"),
            ({"title": "Title"}, "content"),
            ({"title": "T" * 101, "content": "Content"}, "title"),
        ]
        for data, field in cases:
            with self.subTest(data=data):
                response = self.client.post(reverse("note_create"), data)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "notes/note_form.html")
                form = response.context["form"]
                self.assertIn(field, form.errors)
                self.assertContains(response, form.errors[field][0])
                self.assertEqual(Note.objects.count(), 2)

    def test_update_get_prefills_form_without_changing_note(self):
        """Populate the edit form without changing persisted note data."""
        response = self.client.get(reverse("note_update", args=[self.note.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notes/note_form.html")
        form = response.context["form"]
        self.assertEqual(form.instance, self.note)
        self.assertEqual(form.initial["title"], self.note.title)
        self.assertEqual(form.initial["content"], self.note.content)
        self.assert_original_note_unchanged()

    def test_update_changes_data_but_not_owner_or_creation_time(self):
        """Save edits while retaining ownership and the creation timestamp."""
        modified = self.note.updated_at + timedelta(days=1)
        with patch("django.utils.timezone.now", return_value=modified):
            response = self.client.post(
                reverse("note_update", args=[self.note.pk]),
                {
                    "title": "Updated",
                    "content": "Updated content",
                    "owner": self.other.pk,
                    "created_at": "2000-01-01T00:00:00Z",
                    "updated_at": "2000-01-01T00:00:00Z",
                },
            )
        self.assertRedirects(
            response, reverse("note_detail", args=[self.note.pk])
        )
        current = Note.objects.get(pk=self.note.pk)
        self.assertEqual(current.title, "Updated")
        self.assertEqual(current.content, "Updated content")
        self.assertEqual(current.owner, self.owner)
        self.assertEqual(current.created_at, self.note.created_at)
        self.assertEqual(current.updated_at, modified)
        self.assertEqual(Note.objects.count(), 2)
        self.other_note.refresh_from_db()
        self.assertEqual(self.other_note.content, "Private content")

    def test_invalid_update_displays_errors_and_preserves_stored_note(self):
        """Display edit errors without altering any persisted note fields."""
        cases = [
            ({"title": "", "content": "Changed"}, "title"),
            ({"title": "Changed", "content": ""}, "content"),
            ({"title": "T" * 101, "content": "Changed"}, "title"),
        ]
        for data, field in cases:
            with self.subTest(data=data):
                response = self.client.post(
                    reverse("note_update", args=[self.note.pk]), data
                )
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "notes/note_form.html")
                form = response.context["form"]
                self.assertIn(field, form.errors)
                self.assertContains(response, form.errors[field][0])
                self.assert_original_note_unchanged()
                self.assertEqual(Note.objects.count(), 2)

    def test_delete_get_confirms_without_deleting(self):
        """Show deletion confirmation and a cancel link without deleting."""
        response = self.client.get(reverse("note_delete", args=[self.note.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notes/note_confirm_delete.html")
        self.assertContains(response, self.note.title)
        self.assertContains(
            response, reverse("note_detail", args=[self.note.pk])
        )
        self.assert_original_note_unchanged()
        self.assertEqual(Note.objects.count(), 2)

    def test_delete_post_removes_only_selected_note(self):
        """Delete the selected owned note and redirect to the note list."""
        response = self.client.post(
            reverse("note_delete", args=[self.note.pk])
        )
        self.assertRedirects(response, reverse("note_list"))
        self.assertFalse(Note.objects.filter(pk=self.note.pk).exists())
        self.assertTrue(Note.objects.filter(pk=self.other_note.pk).exists())

    def test_nonowners_receive_404_and_cannot_read_or_change_note(self):
        """Return 404 without exposing or changing another user's note."""
        self.client.force_login(self.other)
        for name in ("note_detail", "note_update", "note_delete"):
            for method in ("get", "post"):
                with self.subTest(endpoint=name, method=method):
                    response = getattr(self.client, method)(
                        reverse(name, args=[self.note.pk]),
                        {"title": "Stolen", "content": "Changed"},
                    )
                    self.assertEqual(response.status_code, 404)
                    self.assertNotContains(
                        response, self.note.content, status_code=404
                    )
                    self.assert_original_note_unchanged()
                    self.assertEqual(Note.objects.count(), 2)

    def test_missing_notes_return_404(self):
        """Return 404 for absent notes without changing existing records."""
        missing_pk = self.other_note.pk + self.note.pk + 100
        for name in ("note_detail", "note_update", "note_delete"):
            for method in ("get", "post"):
                with self.subTest(endpoint=name, method=method):
                    response = getattr(self.client, method)(
                        reverse(name, args=[missing_pk]),
                        {"title": "Title", "content": "Content"},
                    )
                    self.assertEqual(response.status_code, 404)
        self.assertEqual(Note.objects.count(), 2)
        self.assert_original_note_unchanged()


class AuthenticationTests(TestCase):
    """Check registration and the application's Django auth integration."""

    password = "Strong-test-password-74!"

    @classmethod
    def setUpTestData(cls):
        """Create an existing account with a valid password for auth tests."""
        cls.user = get_user_model().objects.create_user(
            username="existing", password=cls.password
        )

    def registration_data(self, **overrides):
        """Return valid registration data with optional invalid overrides."""
        data = {
            "username": "newuser",
            "password1": self.password,
            "password2": self.password,
        }
        data.update(overrides)
        return data

    def test_registration_get_displays_form_without_creating_user(self):
        """Show an unbound registration form without creating an account."""
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/register.html")
        self.assertFalse(response.context["form"].is_bound)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_registration_creates_user_hashes_password_and_logs_in(self):
        """Register an account, hash its password, and start its session."""
        response = self.client.post(
            reverse("register"), self.registration_data()
        )
        self.assertRedirects(response, reverse("note_list"))
        self.assertEqual(get_user_model().objects.count(), 2)
        user = get_user_model().objects.get(username="newuser")
        self.assertNotEqual(user.password, self.password)
        self.assertTrue(user.check_password(self.password))
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
        response = self.client.get(reverse("note_list"))
        self.assertEqual(response.status_code, 200)

    def test_invalid_registration_shows_errors_and_creates_no_user(self):
        """Reject invalid account data without registering or logging in."""
        cases = [
            ({"username": "existing"}, "username"),
            ({"username": ""}, "username"),
            ({"password2": "Different-password-84!"}, "password2"),
            ({"password1": "abc", "password2": "abc"}, "password2"),
            ({"password1": "", "password2": ""}, "password1"),
        ]
        for overrides, field in cases:
            with self.subTest(overrides=overrides):
                response = self.client.post(
                    reverse("register"), self.registration_data(**overrides)
                )
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "registration/register.html")
                self.assertIn(field, response.context["form"].errors)
                self.assertEqual(get_user_model().objects.count(), 1)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_authenticated_user_cannot_register_another_account(self):
        """Redirect signed-in users without creating or switching accounts."""
        self.client.force_login(self.user)
        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    reverse("register"), self.registration_data()
                )
                self.assertRedirects(response, reverse("note_list"))
                self.assertEqual(get_user_model().objects.count(), 1)
                self.assertEqual(
                    self.client.session[SESSION_KEY], str(self.user.pk)
                )

    def test_login_get_displays_form(self):
        """Render the login page for an unauthenticated visitor."""
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")

    def test_valid_login_redirects_and_persists_session_across_requests(self):
        """Authenticate valid credentials and retain identity across pages."""
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.password},
        )
        self.assertRedirects(response, reverse("note_list"))
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))
        for name in ("note_list", "note_create"):
            with self.subTest(endpoint=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.wsgi_request.user, self.user)

    def test_invalid_login_does_not_authenticate(self):
        """Show errors for invalid credentials without starting a session."""
        cases = [
            (self.user.username, "Incorrect-password"),
            ("unknown", self.password),
            ("", ""),
        ]
        for username, password in cases:
            with self.subTest(username=username):
                response = self.client.post(
                    reverse("login"),
                    {"username": username, "password": password},
                )
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "registration/login.html")
                self.assertTrue(response.context["form"].errors)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_inactive_user_cannot_log_in(self):
        """Deny login to an inactive account despite a correct password."""
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_returns_user_to_originally_requested_page(self):
        """Honor the local next destination after a successful login."""
        destination = reverse("note_create")
        response = self.client.get(destination)
        self.assertRedirects(
            response, reverse("login") + "?next=" + destination
        )
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": self.password,
                "next": destination,
            },
        )
        self.assertRedirects(response, destination)

    def test_logout_clears_session_and_revokes_note_access(self):
        """End the session and require login for subsequent note requests."""
        self.client.force_login(self.user)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertRedirects(
            self.client.get(reverse("note_list")),
            reverse("login") + "?next=" + reverse("note_list"),
        )
