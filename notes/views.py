from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render

from .forms import NoteForm
from .models import Note


def get_owned_note(request, pk):
    """Return the note if owned by the current user, otherwise 404."""
    return get_object_or_404(Note, pk=pk, owner=request.user)


@login_required
def note_list(request):
    """List the logged-in user's notes, newest first."""
    # Django adds `objects` at runtime; the checker cannot see it.
    notes = Note.objects.filter(owner=request.user)
    return render(request, "notes/note_list.html", {"notes": notes})


@login_required
def note_detail(request, pk):
    """Show a single note owned by the logged-in user."""
    note = get_owned_note(request, pk)
    return render(request, "notes/note_detail.html", {"note": note})


@login_required
def note_create(request):
    """Show the empty note form (GET) or save a new note (POST)."""
    if request.method == "POST":
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.owner = request.user  # owner is set only on creation
            note.save()
            return redirect("note_list")
    else:
        form = NoteForm()
    return render(request, "notes/note_form.html", {"form": form})


@login_required
def note_update(request, pk):
    """Show the note pre-filled in a form (GET) or save changes (POST)."""
    note = get_owned_note(request, pk)
    if request.method == "POST":
        form = NoteForm(request.POST, instance=note)
        if form.is_valid():
            form.save()
            return redirect("note_detail", pk=note.pk)
    else:
        form = NoteForm(instance=note)
    context = {"form": form, "note": note}
    return render(request, "notes/note_form.html", context)


@login_required
def note_delete(request, pk):
    """Ask for confirmation (GET) or delete the note (POST)."""
    note = get_owned_note(request, pk)
    if request.method == "POST":
        note.delete()
        return redirect("note_list")
    return render(request, "notes/note_confirm_delete.html", {"note": note})


def register(request):
    """Create a new user account and log the user in."""
    if request.user.is_authenticated:
        return redirect("note_list")
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("note_list")
    else:
        form = UserCreationForm()
    return render(request, "registration/register.html", {"form": form})
