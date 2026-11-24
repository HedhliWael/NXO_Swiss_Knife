from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length

from ..vendors.factory import registered_vendors

VENDOR_CHOICES = [("", "-- Select vendor --")] + [(v, v) for v in registered_vendors()]


class ProjectForm(FlaskForm):
    name = StringField(
        "Project Name",
        validators=[
            DataRequired(message="Project name is required."),
            Length(min=2, max=100, message="Project name must be between 2 and 100 characters."),
        ],
    )

    description = TextAreaField(
        "Description",
        validators=[Length(max=500, message="Description must be less than 500 characters.")],
    )

    # Firewall slot 1: '' = none, 'new' = create, otherwise an existing firewall id.
    fw1_mode = SelectField("Firewall 1")
    fw1_name = StringField("Name")
    fw1_vendor = SelectField("Vendor", choices=VENDOR_CHOICES)
    fw1_management_ip = StringField("Management IP")

    # Firewall slot 2.
    fw2_mode = SelectField("Firewall 2")
    fw2_name = StringField("Name")
    fw2_vendor = SelectField("Vendor", choices=VENDOR_CHOICES)
    fw2_management_ip = StringField("Management IP")

    submit = SubmitField("Create Project")

    def __init__(self, formdata=None, **kwargs):
        super().__init__(formdata, **kwargs)

        # On pages where the firewall selects are not rendered (edit page),
        # the fields are not submitted; default them to the blank value so
        # SelectField validation does not fail on a missing value.
        for name in ("fw1_mode", "fw1_vendor", "fw2_mode", "fw2_vendor"):
            if self[name].data is None:
                self[name].data = ""

    def set_firewall_choices(self, firewalls):
        """Offer the existing firewalls in the database as options."""
        choices = [("", "-- None --"), ("new", "Create new firewall")]
        choices += [(str(fw.id), f"{fw.name} ({fw.vendor})") for fw in firewalls]
        self.fw1_mode.choices = choices
        self.fw2_mode.choices = choices

    def validate(self, *args, **kwargs):
        valid = super().validate(*args, **kwargs)

        for i in (1, 2):
            mode = getattr(self, "fw%d_mode" % i).data or ""
            if mode != "new":
                continue

            name = getattr(self, "fw%d_name" % i).data.strip()
            vendor = getattr(self, "fw%d_vendor" % i).data

            if not name:
                self["fw%d_name" % i].errors.append(
                    f"Firewall {i}: a name is required when creating a new firewall."
                )
                valid = False
            elif len(name) > 120:
                self["fw%d_name" % i].errors.append(
                    f"Firewall {i}: name is too long (max 120 characters)."
                )
                valid = False
            if not vendor:
                self["fw%d_vendor" % i].errors.append(
                    f"Firewall {i}: a vendor is required when creating a new firewall."
                )
                valid = False

        mode1 = self.fw1_mode.data or ""
        mode2 = self.fw2_mode.data or ""
        if mode1 and mode2 and mode1 == mode2 and mode1 != "new":
            self.fw2_mode.errors.append("The same firewall cannot be selected for both slots.")
            valid = False

        return valid
