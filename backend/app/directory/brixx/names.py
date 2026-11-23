"""Every BRIXX table and column the code reads, in one place.

BRIXX sends its own names (`PRG_SUBOBJECT`, not "VHE"; `WEERGAVENAAM2`, not "naam"), and the code reads rows by those
names. A wrong or stale name does not fail: the reader finds nothing and the screen shows a dash. `READS` is the
contract between the code and the real BRIXX schema (the `BRIXX_MIRROR` literals of the committed migrations):

* each table maps to the column *groups* the code reads from it; a group is a tuple of candidate names and is satisfied
  when at least one of them is a real column of that table (the first real one wins at runtime);
* `tests/unit/directory/brixx/test_names.py` fails when a name is not in the real schema, and when the code reads a
  column group that is not listed here;
* `name_gaps` runs the same comparison against the live mirror (see `name_check.py`) after every mapping run.

Reading a new BRIXX column therefore means: add it to the right table below, in the same change.
"""

from app.directory.brixx import columns as col
from app.directory.brixx import rent_ledger as ledger
from app.directory.brixx import unit_facts as facts

Group = tuple[str, ...]

_ADDRESS: tuple[Group, ...] = (
    col.STREET,
    col.HOUSE_NUMBER,
    col.HOUSE_LETTER,
    col.HOUSE_SUFFIX,
    col.POSTCODE,
    col.CITY,
)
_PERIOD: tuple[Group, ...] = (col.START, col.END)
_ROW: tuple[Group, ...] = (col.DELETED, col.CREATED)

READS: dict[str, tuple[Group, ...]] = {
    col.RELATIE: (
        (col.RELATIE_PK,),
        col.NAME,
        col.EMAIL,
        col.PHONE,
        col.RELATIE_NUMBER,
        col.FIRST_NAME,
        col.NAME_REST,
        *_ROW,
    ),
    col.OBJECT: ((col.OBJECT_PK,), col.OBJECT_LABEL, *_ADDRESS, *_ROW),
    col.VHE: ((col.VHE_PK,), (col.OBJECT_PK,), col.VHE_LABEL, facts.AREA, *_ADDRESS, *_ROW),
    col.CONTRACT: ((col.CONTRACT_PK,), col.CONTRACT_TENANT, facts.DEPOSIT, *_PERIOD, *_ROW),
    col.CONTRACTVHE: ((col.CONTRACTVHE_PK,), (col.CONTRACT_PK,), (col.VHE_PK,), *_PERIOD, *_ROW),
    col.CONTRACTRELATIE: ((col.CONTRACT_PK,), (col.RELATIE_PK,), col.ORDER),
    facts.PAYMENTS: (
        (col.CONTRACT_PK,),
        (facts.COMPONENT_PK,),
        facts.AMOUNT,
        facts.TERM_MONTHS,
        *_PERIOD,
        col.DELETED,
    ),
    facts.COMPONENTS: ((facts.COMPONENT_PK,), ("benaming", "omschrijving")),
    ledger.INVOICE: (
        (ledger.INVOICE_PK,),
        (col.CONTRACT_PK,),
        ledger.PLAN_DATE,
        ledger.DUE_DATE,
        ledger.NUMBER,
        ledger.STATUS,
        ledger.KIND,
        ledger.TOTAL,
        ledger.METHOD,
    ),
    ledger.PAYMENT: (
        (ledger.PAYMENT_PK,),
        (ledger.INVOICE_PK,),
        ledger.PAID,
        ledger.PAID_ON,
        ledger.REVERSED,
    ),
    # Tenant documents (app/directory/brixx/tenant_documents.py): columns are named there with their types.
    "prg_document": (
        ("prg_documentid",),
        ("benaming",),
        ("filenaam",),
        ("groottebytes",),
        ("typ_documentcategorieid",),
        col.CREATED,
    ),
    "prg_relatiedocument": (
        ("prg_documentid",),
        (col.RELATIE_PK,),
        ("typ_relatiedocumentid",),
        ("indverwijderd",),
    ),
    "prg_document_link": (("prg_documentid",), ("entiteitid",), ("sys_entiteittypeid",)),
    "typ_documentcategorie": (("typ_documentcategorieid",), ("benaming",)),
    "typ_relatiedocument": (("typ_relatiedocumentid",), ("benaming",)),
    # Maintenance feed (app/api/maintenance/brixx_tickets.py); its own names are literals there, kept equal by the test.
    "tst_ticket": (
        ("tst_ticketid",),
        (col.RELATIE_PK,),
        (col.VHE_PK,),
        ("typ_tickettypeid",),
        ("tst_ticket_locatieid",),
        ("dmticketstatus",),
        ("datumgesloten",),
        ("dienstverlenerid",),
        ("titel", "omschrijving"),
        ("titel",),
        ("indurgent",),
        *_ROW,
    ),
    "typ_tickettype": (("typ_tickettypeid",), ("benaming", "omschrijving")),
    "tst_ticket_locatie": (("tst_ticket_locatieid",), ("benaming", "omschrijving")),
    "tst_ticketbericht": (("tst_ticketberichtid",), ("actiedatum",), ("bericht",), col.CREATED),
}
