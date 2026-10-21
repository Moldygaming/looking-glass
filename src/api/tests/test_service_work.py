import unittest

from app.connectors.azure_devops import (
    escape_wiql_literal,
    normalize_work_item,
    work_item_is_open,
    work_item_top,
    work_item_wiql,
)
from app.connectors.freshservice import (
    agent_directory,
    assignment_warning,
    normalize_record,
    parse_domain,
    priority_label,
    record_is_open,
    skip_missing_module,
    status_label,
)
from app.services.service_desk import assigned_to_user_clause
from app.services.service_records import clip


class DomainParseTests(unittest.TestCase):
    def test_subdomain(self):
        label, base = parse_domain({"domain": "acme"})
        self.assertEqual(label, "acme")
        self.assertEqual(base, "https://acme.freshservice.com")

    def test_host(self):
        label, base = parse_domain({"domain": "Acme.freshservice.com"})
        self.assertEqual(label, "acme")
        self.assertEqual(base, "https://acme.freshservice.com")

    def test_url(self):
        label, base = parse_domain({"domain": "https://acme.freshservice.com/a/tickets/1"})
        self.assertEqual(label, "acme")
        self.assertEqual(base, "https://acme.freshservice.com")

    def test_missing(self):
        with self.assertRaises(Exception):
            parse_domain({})

    def test_spaces_rejected(self):
        with self.assertRaises(Exception):
            parse_domain({"domain": "not a domain"})


class FreshserviceRecordTests(unittest.TestCase):
    def test_open_ticket(self):
        row = normalize_record(
            "ticket",
            {
                "id": 42,
                "subject": "VPN down",
                "status": 2,
                "priority": 3,
                "type": "Incident",
                "requester": {"name": "Ada"},
                "created_at": "2026-01-02T03:04:05Z",
                "updated_at": "2026-01-03T03:04:05Z",
            },
            "https://acme.freshservice.com",
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.kind, "ticket")
        self.assertEqual(row.title, "VPN down")
        self.assertEqual(row.state, "Open")
        self.assertEqual(row.priority, "High")
        self.assertEqual(row.requester, "Ada")
        self.assertEqual(row.item_type, "Incident")
        self.assertTrue(row.is_open)
        self.assertEqual(row.url, "https://acme.freshservice.com/a/tickets/42")
        self.assertIsNotNone(row.updated_at)

    def test_closed_ticket_and_custom_status(self):
        closed = normalize_record("ticket", {"id": 1, "subject": "Done", "status": 5}, "https://acme.freshservice.com")
        custom = normalize_record("ticket", {"id": 2, "subject": "Waiting", "status": 8}, "https://acme.freshservice.com")
        assert closed is not None and custom is not None
        self.assertFalse(closed.is_open)
        self.assertEqual(closed.state, "Closed")
        self.assertTrue(custom.is_open)
        self.assertEqual(custom.state, "Status 8")

    def test_problem_and_change(self):
        problem = normalize_record("problem", {"id": 7, "subject": "Mail loop", "status": 3, "priority": 1}, "https://acme.freshservice.com")
        change = normalize_record(
            "change",
            {"id": 9, "subject": "Patch window", "status": 1, "priority": 4, "change_type": 4},
            "https://acme.freshservice.com",
        )
        assert problem is not None and change is not None
        self.assertFalse(problem.is_open)
        self.assertEqual(problem.state, "Closed")
        self.assertEqual(problem.url, "https://acme.freshservice.com/a/problems/7")
        self.assertTrue(change.is_open)
        self.assertEqual(change.item_type, "Emergency change")
        self.assertEqual(change.priority, "Urgent")
        self.assertEqual(change.url, "https://acme.freshservice.com/a/changes/9")

    def test_missing_id(self):
        self.assertIsNone(normalize_record("ticket", {"subject": "nope"}, "https://acme.freshservice.com"))

    def test_assignee_from_agent_id(self):
        agents = agent_directory(
            [
                {"id": "15", "first_name": "Luke", "last_name": "Dowsett", "email": "Luke@Contoso.com"},
                {"first_name": "Skipped"},
                "not-a-row",
            ]
        )
        self.assertEqual(agents[15], ("Luke Dowsett", "Luke@Contoso.com"))
        record = normalize_record(
            "ticket",
            {"id": 42, "subject": "VPN down", "status": 2, "responder_id": 15},
            "https://acme.freshservice.com",
            agents,
        )
        assert record is not None
        self.assertEqual(record.assignee, "Luke@Contoso.com")
        self.assertEqual(record.assignee_email, "Luke@Contoso.com")
        problem = normalize_record(
            "problem",
            {"id": 8, "subject": "Loop", "status": 1, "agent_id": 15},
            "https://acme.freshservice.com",
            agents,
        )
        assert problem is not None
        self.assertEqual(problem.assignee_email, "Luke@Contoso.com")

    def test_agent_directory_indexes_user_id_and_primary_email(self):
        directory = agent_directory(
            [
                {
                    "agent": {
                        "id": 19,
                        "user": {"id": 2, "name": "Optimus Prime", "email": "prime@transformers.com"},
                    }
                },
                {"id": 8, "first_name": "Ada", "primary_email": "ada@contoso.com"},
            ]
        )
        self.assertEqual(directory[19], ("Optimus Prime", "prime@transformers.com"))
        self.assertEqual(directory[2], ("Optimus Prime", "prime@transformers.com"))
        self.assertEqual(directory[8], ("Ada", "ada@contoso.com"))
        record = normalize_record(
            "ticket",
            {"id": 1, "subject": "Mail", "status": 2, "responder_id": 19, "requester_id": 8},
            "https://acme.freshservice.com",
            directory,
        )
        assert record is not None
        self.assertEqual(record.assignee, "prime@transformers.com")
        self.assertEqual(record.assignee_email, "prime@transformers.com")
        self.assertEqual(record.requester, "Ada")
        self.assertTrue(assignment_warning(4, 0))
        self.assertEqual(assignment_warning(4, 1), "")
        self.assertEqual(assignment_warning(0, 0), "")

    def test_embedded_person_email(self):
        record = normalize_record(
            "ticket",
            {"id": 3, "subject": "Mail", "status": 2, "responder": {"name": "Ada", "email": "ada@contoso.com"}},
            "https://acme.freshservice.com",
        )
        assert record is not None
        self.assertEqual(record.assignee, "ada@contoso.com")
        self.assertEqual(record.assignee_email, "ada@contoso.com")

    def test_labels_and_skip(self):
        self.assertEqual(status_label("problem", 2), "Change Requested")
        self.assertEqual(priority_label(2), "Medium")
        self.assertTrue(record_is_open("change", 5))
        self.assertFalse(record_is_open("change", 6))
        self.assertTrue(skip_missing_module("problem", 404))
        self.assertFalse(skip_missing_module("ticket", 404))
        self.assertFalse(skip_missing_module("change", 401))


class WorkItemTests(unittest.TestCase):
    def test_wiql_uses_project_macro_and_escapes_names(self):
        query = work_item_wiql()
        self.assertIn("[System.TeamProject] = @project", query)
        self.assertNotIn("TOP", query.upper())
        self.assertIn("[System.State] <> 'Removed'", query)
        named = work_item_wiql("O'Brien")
        self.assertIn("[System.TeamProject] = 'O''Brien'", named)
        self.assertEqual(escape_wiql_literal("a'b"), "a''b")
        self.assertEqual(work_item_top(500), 200)
        self.assertEqual(work_item_top(0), 1)

    def test_normalize_open_item(self):
        record = normalize_work_item(
            {
                "id": 12,
                "fields": {
                    "System.Title": "Ship the portal",
                    "System.WorkItemType": "User Story",
                    "System.State": "Active",
                    "System.AssignedTo": {"displayName": "Grace"},
                    "System.TeamProject": "My Project",
                    "Microsoft.VSTS.Common.Priority": 2,
                    "System.ChangedDate": "2026-02-01T12:00:00Z",
                },
            },
            org_url="https://dev.azure.com/contoso",
            project_name="My Project",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.source, "azure_devops")
        self.assertEqual(record.kind, "work_item")
        self.assertEqual(record.external_id, "12")
        self.assertEqual(record.assignee, "Grace")
        self.assertEqual(record.assignee_email, "")
        self.assertEqual(record.item_type, "User Story")
        self.assertEqual(record.priority, "2")
        self.assertTrue(record.is_open)
        self.assertEqual(record.url, "https://dev.azure.com/contoso/My%20Project/_workitems/edit/12")

    def test_assignee_email_from_unique_name_or_angle_address(self):
        with_mail = normalize_work_item(
            {
                "id": 4,
                "fields": {
                    "System.Title": "Mine",
                    "System.AssignedTo": {"displayName": "Luke Dowsett", "uniqueName": "luke@contoso.com"},
                },
            },
            org_url="https://dev.azure.com/contoso",
            project_name="Proj",
        )
        assert with_mail is not None
        self.assertEqual(with_mail.assignee, "luke@contoso.com")
        self.assertEqual(with_mail.assignee_email, "luke@contoso.com")
        domain_account = normalize_work_item(
            {
                "id": 5,
                "fields": {"System.AssignedTo": {"displayName": "Grace", "uniqueName": "CONTOSO\\grace"}},
            },
            org_url="https://dev.azure.com/contoso",
            project_name="Proj",
        )
        assert domain_account is not None
        self.assertEqual(domain_account.assignee, "Grace")
        self.assertEqual(domain_account.assignee_email, "")
        written = normalize_work_item(
            {"id": 6, "fields": {"System.AssignedTo": "Ada Lovelace <ada@contoso.com>"}},
            org_url="https://dev.azure.com/contoso",
            project_name="Proj",
        )
        assert written is not None
        self.assertEqual(written.assignee, "ada@contoso.com")
        self.assertEqual(written.assignee_email, "ada@contoso.com")

    def test_assigned_clause_uses_upn_not_display_name(self):
        mine = str(
            assigned_to_user_clause(["Luke@Contoso.com", "luke@contoso.com", ""]).compile(
                compile_kwargs={"literal_binds": True}
            )
        ).lower()
        self.assertIn("assignee_email", mine)
        self.assertIn("luke@contoso.com", mine)
        self.assertNotIn("luke dowsett", mine)
        self.assertNotIn("like", mine)
        nobody = str(assigned_to_user_clause(["", " "]).compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("false", nobody)

    def test_closed_states(self):
        self.assertFalse(work_item_is_open("Done"))
        self.assertFalse(work_item_is_open("Completed"))
        self.assertTrue(work_item_is_open("Resolved"))
        record = normalize_work_item(
            {"id": 3, "fields": {"System.State": "Closed", "System.Title": "Old"}},
            org_url="https://dev.azure.com/contoso",
            project_name="Proj",
        )
        assert record is not None
        self.assertFalse(record.is_open)

    def test_missing_work_item_id(self):
        self.assertIsNone(normalize_work_item({"fields": {}}, org_url="https://dev.azure.com/contoso", project_name="Proj"))

    def test_clip(self):
        self.assertEqual(clip("  abc  ", 2), "ab")
        self.assertEqual(clip(None, 4), "")
