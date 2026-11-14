"""Dashboard sections a profile can be granted, and what a signed-in person may open (ADR 0012)."""

from dataclasses import dataclass
from typing import NamedTuple


class Section(NamedTuple):
    key: str
    label: str
    description: str


SECTIONS: tuple[Section, ...] = (
    Section("dashboard", "Dashboard", "Today's overview and what needs attention"),
    Section("inbox", "Messages", "WhatsApp and email conversations, drafts and approvals"),
    Section("properties", "Properties", "Buildings, units and occupancy"),
    Section("tenants", "Tenants", "Tenant profiles, leases and rent status"),
    Section("contacts", "Contacts", "Tenants, contractors and other people, and adding new ones"),
    Section("maintenance", "Maintenance", "Tickets, contractors and quotes"),
    Section("money", "Money", "Rent, quotes and finance"),
    Section("reports", "Reports", "Portfolio reports and exports"),
    Section("settings", "Settings", "Memory rules, persona and integrations"),
)
SECTION_KEYS: frozenset[str] = frozenset(s.key for s in SECTIONS)
DATA_SECTION_KEYS: frozenset[str] = SECTION_KEYS - {"settings"}  # what the Super Agent reads from
ADMIN_ROLES: frozenset[str] = frozenset({"owner", "superadmin"})  # full access, and the only ones who manage profiles


@dataclass(frozen=True)
class Access:
    """What one signed-in person may open. `sections=None` means every section."""

    role: str = "owner"
    sections: frozenset[str] | None = None

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES

    def can(self, section: str) -> bool:
        return self.is_admin or self.sections is None or section in self.sections

    @property
    def can_use_agent(self) -> bool:
        """The Super Agent answers from the whole portfolio, so it is for profiles that open every data section."""
        return self.is_admin or self.sections is None or self.sections >= DATA_SECTION_KEYS

    def visible_sections(self) -> list[str]:
        return [s.key for s in SECTIONS if self.can(s.key)]
