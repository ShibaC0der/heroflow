from flow.story_sdd.add_sdd_label import add_sdd_label
from flow.story_sdd.attach_spec_file_to_jira_task import attach_spec_file_to_jira_task
from flow.story_sdd.create_pull_request import create_pull_request
from flow.story_sdd.explore import explore
from flow.story_sdd.human_review_impl import human_review_impl
from flow.story_sdd.human_review_proposal import human_review_proposal
from flow.story_sdd.opsx_apply import opsx_apply
from flow.story_sdd.opsx_propose import opsx_propose
from flow.story_sdd.opsx_verify import opsx_verify
from flow.story_sdd.remove_unnecessary_spec_changes import remove_unnecessary_spec_changes
from flow.story_sdd.resolve_delta_spec_dir import resolve_delta_spec_dir
from flow.story_sdd.review_proposal import review_proposal

STEPS = [
    explore,
    opsx_propose,
    resolve_delta_spec_dir,
    add_sdd_label,
    review_proposal,
    create_pull_request,
    human_review_proposal,
    opsx_apply,
    opsx_verify,
    human_review_impl,
    attach_spec_file_to_jira_task,
    remove_unnecessary_spec_changes,
]
