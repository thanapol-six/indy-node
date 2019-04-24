import json
import random
from abc import ABCMeta, abstractmethod

import pytest
from indy.did import replace_keys_start, replace_keys_apply

from indy_common.authorize.auth_actions import ADD_PREFIX, split_action_id, AuthActionAdd, EDIT_PREFIX, AuthActionEdit
from indy_common.authorize.auth_constraints import ROLE, IDENTITY_OWNER, AbstractAuthConstraint, ConstraintsEnum, \
    accepted_roles, AuthConstraint
from indy_common.constants import NYM, TRUST_ANCHOR, TRUST_ANCHOR_STRING, NETWORK_MONITOR_STRING, NETWORK_MONITOR
from indy_node.test.auth_rule.auth_framework.basic import AbstractTest, roles_to_string
from indy_node.test.auth_rule.helper import create_verkey_did, generate_auth_rule_operation
from indy_node.test.helper import sdk_rotate_verkey
from plenum.common.constants import STEWARD_STRING, STEWARD, TRUSTEE, TRUSTEE_STRING, IDENTITY_OWNER_STRING, VERKEY
from plenum.common.exceptions import RequestRejectedException
from plenum.common.util import randomString
from plenum.test.helper import sdk_gen_request, sdk_sign_and_submit_req_obj, sdk_get_and_check_replies, \
    sdk_json_to_request_object, sdk_multi_sign_request_objects, sdk_send_signed_requests
from plenum.test.pool_transactions.helper import prepare_nym_request, sdk_add_new_nym
from indy_common.authorize import auth_map
from plenum.test.testing_utils import FakeSomething


class AddNewRoleTest(AbstractTest):
    def __init__(self, role, creator_wallet, env):
        self.role = role
        self.role_string = roles_to_string[self.role]
        self.creator_wallet = creator_wallet
        self.looper = env.looper
        self.sdk_pool_handle = env.sdk_pool_handle

        self.reqs = []
        self.auth_rule_reqs = []

    def prepare(self):
        self.phase_req_1 = self.get_nym()
        self.phase_req_2 = self.get_nym()
        self.phase_req_3 = self.get_nym()

        self.default_auth_rule = self.get_default_auth_rule()
        self.changed_auth_rule = self.get_changed_auth_rule()


    def run(self):
        # Step 1. Check default auth rule
        self.send_and_check(self.phase_req_1)

        # Step 2. Change auth rule
        self.send_and_check(self.changed_auth_rule)

        # Step 3. Check, that we cannot add new steward by old way
        with pytest.raises(RequestRejectedException):
            self.send_and_check(self.phase_req_2)

        # Step 4. Return default auth rule
        self.send_and_check(self.default_auth_rule)

        # Step 5. Check, that default auth rule works
        self.send_and_check(self.phase_req_3)

    def result(self):
        pass


    def send_and_check(self, req):
        signed_reqs = sdk_multi_sign_request_objects(self.looper,
                                                     [self.creator_wallet],
                                                     [req])
        request_couple = sdk_send_signed_requests(self.sdk_pool_handle,
                                                  signed_reqs)[0]

        return sdk_get_and_check_replies(self.looper,
                                         [request_couple])[0]

    def get_nym(self):
        wh, _ = self.creator_wallet
        did, _ = create_verkey_did(self.looper, wh)
        return self._build_nym(self.creator_wallet, self.role_string, did)

    def get_default_auth_rule(self):
        action = AuthActionAdd(NYM, ROLE, value=self.role)
        constraint = auth_map.auth_map.get(action.get_action_id())
        operation = generate_auth_rule_operation(auth_action=ADD_PREFIX,
                                                 auth_type=NYM,
                                                 field=ROLE,
                                                 new_value=self.role,
                                                 constraint=constraint.as_dict)
        return sdk_gen_request(operation, identifier=self.creator_wallet[1])

    def get_changed_auth_rule(self):
        constraint = AuthConstraint(role=TRUST_ANCHOR,
                                    sig_count=1,
                                    need_to_be_owner=False)
        operation = generate_auth_rule_operation(auth_action=ADD_PREFIX,
                                                 auth_type=NYM,
                                                 field=ROLE,
                                                 new_value=self.role,
                                                 constraint=constraint.as_dict)
        return sdk_gen_request(operation, identifier=self.creator_wallet[1])


class AddNewStewardTest(AddNewRoleTest):
    def __init__(self, env):
        super().__init__(STEWARD, env.sdk_wallet_trustee, env)


class AddNewTrusteeTest(AddNewRoleTest):
    def __init__(self, env):
        super().__init__(TRUSTEE, env.sdk_wallet_trustee, env)


class AddNewTrustAnchorTest(AddNewRoleTest):
    def __init__(self, env):
        super().__init__(TRUST_ANCHOR, env.sdk_wallet_trustee, env)


class AddNewNetworkMonitorTest(AddNewRoleTest):
    def __init__(self, env):
        super().__init__(NETWORK_MONITOR, env.sdk_wallet_trustee, env)


class AddNewIdentityOwnerTest(AddNewRoleTest):
    def __init__(self, env):
        super().__init__(IDENTITY_OWNER, env.sdk_wallet_trustee, env)


class EditTrusteeTest(AbstractTest):
    def __init__(self, role, action_id: str, constraint: AbstractAuthConstraint, env):
        self.role = role
        self.role_string = roles_to_string[self.role]
        self.trustee_wallet = env.sdk_wallet_trustee
        self.action_def = split_action_id(action_id)
        self.constraint = constraint
        self.env = env
        self.default_constraint_roles = []
        self.other_roles = []
        self.checker_wallet = None
        self.default_wallet = None
        self.new_default_did = None
        self.role_to_change = None

    def prepare(self):
        self.default_constraint_roles = self.get_default_roles(self.constraint)
        self.other_roles = set(accepted_roles).difference(set(self.default_constraint_roles).union({NETWORK_MONITOR}))
        self.new_default_did = self.create_role()

    def get_default_roles(self, constraint):
        d_roles = []
        if constraint.constraint_id != ConstraintsEnum.ROLE_CONSTRAINT_ID:
            for a_c in constraint.auth_constraints:
                self.get_default_roles(a_c)
        d_roles.append(constraint.role)
        return d_roles

    def create_role(self):
        add_new_trustee = AddNewTrusteeTest(self.env)
        new_trustee_nym = add_new_trustee.get_nym()
        return add_new_trustee.send_and_check(new_trustee_nym)

    def _get_default_edit_nym(self):
        return self._build_nym(self.default_wallet,
                               roles_to_string[random.choice(set(accepted_roles).difference(self.role))],
                               self.new_default_did)

    def _return_to_default_nym(self):
        return self._build_nym(self.default_wallet,
                               self.role_string,
                               self.new_default_did)

    def get_changed_auth_rule(self):
        new_role = random.choice(set(accepted_roles).difference(set(self.other_roles)))
        self.checker_wallet = self.env.role_to_wallet[new_role]
        self.role_to_change = new_role
        constraint = AuthConstraint(role=new_role,
                                    sig_count=1,
                                    need_to_be_owner=False)
        operation = generate_auth_rule_operation(auth_action=self.action_def.prefix,
                                                 auth_type=self.action_def.txn_type,
                                                 field=self.action_def.field,
                                                 old_value=self.action_def.old_value,
                                                 new_value=self.action_def.new_value,
                                                 constraint=constraint.as_dict)
        return sdk_gen_request(operation, identifier=self.trustee_wallet[1])


class RotateKeyTest(AbstractTest):
    def __init__(self, env):
        self.looper = env.looper
        self.sdk_pool_handle = env.sdk_pool_handle
        self.creator_wallet = env.sdk_wallet_trustee

        self.default_auth_rule = None
        self.changed_auth_rule = None
        self.test_nym = None

    def prepare(self):
        self.test_nym = sdk_add_new_nym(self.looper, self.sdk_pool_handle, self.creator_wallet, role=None)
        self.default_auth_rule = self.get_default_auth_rule()
        self.changed_auth_rule = self.get_changed_auth_rule()

    def run(self):
        wh, client_did = self.test_nym
        _, trustee_did = self.creator_wallet

        # Step 1. Check default auth rule
        sdk_rotate_verkey(self.looper, self.sdk_pool_handle, wh, client_did, client_did)
        verkey = self.sdk_modified_verkey_rotate(self.sdk_pool_handle, wh, trustee_did, client_did)

        # Step 2. Change auth rule
        self.send_and_check(self.changed_auth_rule)

        # Step 3. Check, that we cannot add new steward by old way
        sdk_rotate_verkey(self.looper, self.sdk_pool_handle, wh, trustee_did, client_did, verkey)
        verkey = self.sdk_modified_verkey_rotate(self.sdk_pool_handle, wh, client_did, client_did)

        # Step 4. Return default auth rule
        self.send_and_check(self.default_auth_rule)

        # Step 5. Check, that default auth rule works
        sdk_rotate_verkey(self.looper, self.sdk_pool_handle, wh, client_did, client_did, verkey)
        self.sdk_modified_verkey_rotate(self.sdk_pool_handle, wh, trustee_did, client_did)


    def result(self):
        pass

    def get_nym(self, role):
        wh, _ = self.creator_wallet
        did, _ = create_verkey_did(self.looper, wh)
        return self._build_nym(self.creator_wallet, role, did)

    def get_default_auth_rule(self):
        action = AuthActionEdit(NYM, VERKEY, old_value='*', new_value='*')
        constraint = auth_map.auth_map.get(action.get_action_id())
        operation = generate_auth_rule_operation(auth_action=EDIT_PREFIX,
                                                 auth_type=NYM,
                                                 field=VERKEY,
                                                 old_value='*',
                                                 new_value='*',
                                                 constraint=constraint.as_dict)
        return sdk_gen_request(operation, identifier=self.creator_wallet[1])

    def get_changed_auth_rule(self):
        constraint = AuthConstraint(role=TRUSTEE,
                                    sig_count=1,
                                    need_to_be_owner=False)
        operation = generate_auth_rule_operation(auth_action=EDIT_PREFIX,
                                                 auth_type=NYM,
                                                 field=VERKEY,
                                                 old_value='*',
                                                 new_value='*',
                                                 constraint=constraint.as_dict)
        return sdk_gen_request(operation, identifier=self.creator_wallet[1])

    def send_and_check(self, req):
        signed_reqs = sdk_multi_sign_request_objects(self.looper,
                                                     [self.creator_wallet],
                                                     [req])
        request_couple = sdk_send_signed_requests(self.sdk_pool_handle,
                                                  signed_reqs)[0]

        return sdk_get_and_check_replies(self.looper, [request_couple])[0]

    def sdk_modified_verkey_rotate(self, sdk_pool_handle, wh,
                                   did_of_changer,
                                   did_of_changed):
        verkey = self.looper.loop.run_until_complete(
            replace_keys_start(wh, did_of_changed, json.dumps({})))

        with pytest.raises(RequestRejectedException):
            sdk_add_new_nym(self.looper, sdk_pool_handle,
                            (wh, did_of_changer), dest=did_of_changed,
                            verkey=verkey)
        return verkey


class TestAuthRuleUsing():
    map_of_tests = {
        auth_map.add_new_trustee.get_action_id(): AddNewTrusteeTest,
        auth_map.add_new_steward.get_action_id(): AddNewStewardTest,
        auth_map.add_new_trust_anchor.get_action_id(): AddNewTrustAnchorTest,
        auth_map.add_new_network_monitor.get_action_id(): AddNewNetworkMonitorTest,
        auth_map.add_new_identity_owner.get_action_id(): AddNewIdentityOwnerTest,
        auth_map.key_rotation.get_action_id(): RotateKeyTest,
    }

    @pytest.fixture(scope="module")
    def env(self,
            looper,
            sdk_pool_handle,
            sdk_wallet_trustee,
            sdk_wallet_steward,
            sdk_wallet_trust_anchor,
            sdk_wallet_client):
        role_to_wallet = {
            TRUSTEE: sdk_wallet_trustee,
            STEWARD: sdk_wallet_steward,
            TRUST_ANCHOR: sdk_wallet_trust_anchor,
            IDENTITY_OWNER: sdk_wallet_client,
        }
        return FakeSomething(looper=looper,
                             sdk_pool_handle=sdk_pool_handle,
                             sdk_wallet_trustee=sdk_wallet_trustee,
                             sdk_wallet_steward=sdk_wallet_steward,
                             sdk_wallet_client=sdk_wallet_client,
                             role_to_wallet=role_to_wallet)

    @pytest.fixture(scope='module', params=[(k, v) for k, v in map_of_tests.items()])
    def auth_rule_tests(self, request, env):
        action_id, test_cls = request.param
        test = test_cls(env)
        return action_id, test

    def test_auth_rule_using(self, auth_rule_tests):
        descr, test = auth_rule_tests
        print("Running test: {}".format(descr))
        test.prepare()
        test.run()
        test.result()
