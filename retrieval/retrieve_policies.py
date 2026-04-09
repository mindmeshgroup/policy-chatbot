from typing import List, Dict
def retrieve_policies(question: str, role: str = "Student", max_k: int = 3) -> List[Dict]:
    """
    STUB: Mock implementation for retrieval part
    Returns RRF search results from the database
    """
    
    # fallback for data not found
    unsupported_keywords = ["pizza", "coffee", "weather", "nonsense"]
    if any(word in question.lower() for word in unsupported_keywords):
        return []

    # results for the question "What are the rules for late submission?"
    return [
  {
    # layer 1: decision group
    # Core data used by the LLM to generate the answer
    "score": 1.0,
    "content": "## Overdue Submission of Assessment Tasks\n\n(22) The standard penalty for the late submission of an assessment task without or beyond an approved Short\n\nExtension will be five per cent of the total possible mark for the task (ie 5% of 100%) per calendar day that the task is overdue. Where a student is subsequently granted Special Consideration the penalty is removed.\n\n- (23) Work will not be assessed if the submission is overdue by more than five (5) calendar days after:\n2. the original submission date without an approved extension; or a.\n3. any approved extension for that student (including those granted under any Learning Access Plan or Special b. Consideration application).",
    "has_table": False,
    "is_exception": False,

    # layer 2: citation group
    # Metadata passed to the UI for source cards
    "document_title": "Assessment Procedure - Adjustments (including Special Consideration)",
    "source_url": "https://policies.latrobe.edu.au/",
    "escalation_contact": "University Administration",
    "breadcrumb": "Assessment Procedure - Adjustments (including Special Consideration) > Overdue Submission of Assessment Tasks",
    "document_summary": "Policy regarding Assessment Procedure - Adjustments (including Special Consideration).",

    # layer 3: validation group
    # Used for access control and filtering
    "doc_type": "Procedure",
    "category": [
      "Academic",
      "Assessment"
    ],
    "access_level": "Public",
    "target_cohort": [
      "Student",
      "Staff"
    ],
    "campus_scope": [
      "All Campuses"
    ],

    # layer 4 : administrative group
    # Database tracking and chunking logic
    "document_id": "98822ce50da0",
    "approval_body": "Academic Board",
    "department_owner": "University Administration",
    "status": "Current",
    "effective_date": None,
    "review_date": None,
    "superseded_by": None,
    "chunk_id": "a3f41c54e9597bb2",
    "chunk_index": 18,
    "chunk_type": "Text",
    "exception_scope": [],
    "parent_rule_id": None,
    "override_priority": 1
  },
  {
    # layer 1: decision group
    # Core data used by the LLM to generate the answer
    "score": 0.6667,
    "content": "## Late Applications\n\n- (32) An application for Special Consideration submitted after the due date of the assessment task (apart from those who have attempted a point-in-time task or examination) is considered late. In these circumstances students are required to outline and provide evidence for the exceptional circumstances that prevented them from applying on time.\n- (33) Exceptional circumstances must have occurred during the period in which an application would normally be made and be accompanied by evidence for the delay. The circumstances must have been experienced directly by the student, or, if not, students must be able to demonstrate how they have been impacted. Such circumstances are limited to:\n3. medical incapacitation or hospitalisation; a.\n4. an emergency event, such as an accident; b.\n5. death of a significant other or close family member; c.\n6. an exacerbation of a condition provided for in a LAP. d.\n- (34) Applications for Special Consideration cannot be accepted where the results for a subject have already been released.\n- (35) Students that have a LAP should submit an application for Special Consideration where their existing circumstances have been exacerbated, or for new circumstances that require further adjustments that are not stipulated in their LAP.\n- (36) Students are not eligible for Special Consideration if, at the time of application, they have already submitted the relevant assessment task for marking (this does not include a point-in-time assessment or examination - see below).\n- (37) Students who have submitted an application for Special Consideration (for tasks other than an examination or point-in-time assessment) are advised to continue working on their assessment task and, where possible, to submit the task while they are awaiting the outcome of their application. Students should note that any extension granted as an outcome of their application will take into account any elapsed time that has passed during the processing of the application.\n- (38) Students may submit an application for Special Consideration for an examination or a point-in-time assessment task (such as a presentation or a lab), where they can demonstrate that their performance was impacted by illness or an unforeseen circumstance.",
    "has_table": False,
    "is_exception": True,

    # layer 2: citation group
    # Metadata passed to the UI for source cards
    "document_title": "Assessment Procedure - Adjustments (including Special Consideration)",
    "source_url": "https://policies.latrobe.edu.au/",
    "escalation_contact": "University Administration",
    "breadcrumb": "Assessment Procedure - Adjustments (including Special Consideration) > Late Applications",
    "document_summary": "Policy regarding Assessment Procedure - Adjustments (including Special Consideration).",

    # layer 3: validation group
    # Used for access control and filtering
    "doc_type": "Procedure",
    "category": [
      "Academic",
      "Assessment"
    ],
    "access_level": "Public",
    "target_cohort": [
      "Student",
      "Staff"
    ],
    "campus_scope": [
      "All Campuses"
    ],

    # layer 4 : administrative group
    # Database tracking and chunking logic
    "document_id": "98822ce50da0",
    "approval_body": "Academic Board",
    "department_owner": "University Administration",
    "status": "Current",
    "effective_date": None,
    "review_date": None,
    "superseded_by": None,
    "chunk_id": "fd9b5fa714f00161",
    "chunk_index": 24,
    "chunk_type": "Text",
    "exception_scope": [],
    "parent_rule_id": None,
    "override_priority": 1
  },
  {
     # layer 1: decision group
    # Core data used by the LLM to generate the answer
    "score": 0.5,
    "content": "## Late Applications - Students With a LAP That Includes Provisions for Extensions\n\n(19) Students with a LAP with relevant adjustments who apply for an extension after the due date of their assessment will be granted the seven(7)-calendar-day extension. The extension will apply from the original due date of their assessment (e.g., an application that is submitted five (5) calendar days late will be granted a two(2)-calendar-day extension).",
    "has_table": False,
    "is_exception": False,

    # layer 2: citation group
    # Metadata passed to the UI for source cards
    "document_title": "Assessment Procedure - Adjustments (including Special Consideration)",
    "source_url": "https://policies.latrobe.edu.au/",
    "escalation_contact": "University Administration",
    "breadcrumb": "Assessment Procedure - Adjustments (including Special Consideration) > Late Applications - Students With a LAP That Includes Provisions for Extensions",
    "document_summary": "Policy regarding Assessment Procedure - Adjustments (including Special Consideration).",

    # layer 3: validation group
    # Used for access control and filtering
    "doc_type": "Procedure",
    "category": [
      "Academic",
      "Assessment"
    ],
    "access_level": "Public",
    "target_cohort": [
      "Student",
      "Staff"
    ],
    "campus_scope": [
      "All Campuses"
    ],

   # layer 4 : administrative group
    # Database tracking and chunking logic
    "document_id": "98822ce50da0",
    "approval_body": "Academic Board",
    "department_owner": "University Administration",
    "status": "Current",
    "effective_date": None,
    "review_date": None,
    "superseded_by": None,
    "chunk_id": "d585495d052a71e7",
    "chunk_index": 16,
    "chunk_type": "Text",
    "exception_scope": [],
    "parent_rule_id": None,
    "override_priority": 1
  }
]

if __name__ == "__main__":
    res = retrieve_policies("What are the rules for late submission?")
    print(f"Returned {len(res)} chunks for integration testing.")