from django import forms

from .models import Note


class NoteForm(forms.ModelForm):
    """Form for entering and editing a sticky note's title and content."""

    class Meta:
        model = Note
        fields = ["title", "content"]
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Note title"}
            ),
            "content": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 6,
                    "placeholder": "Write your note here",
                }
            ),
        }
