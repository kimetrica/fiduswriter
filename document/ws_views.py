import uuid
import atexit

from document.helpers.session_user_info import SessionUserInfo
from document.helpers.filtering_comments import filter_comments_by_role
from ws.base import BaseWebSocketHandler
from logging import info, error
from tornado.escape import json_decode, json_encode
from tornado.websocket import WebSocketClosedError
from document.models import AccessRight
from document.views import get_accessrights
from avatar.templatetags.avatar_tags import avatar_url

class DocumentWS(BaseWebSocketHandler):
    sessions = dict()
    user_info = SessionUserInfo()

    def open(self, document_id):
        print 'Websocket opened'
        current_user = self.get_current_user()
        document, can_access = self.user_info.init_access(document_id, current_user)

        if can_access:
            if document.id not in DocumentWS.sessions:
                DocumentWS.sessions[document.id]=dict()
                self.id = 0
                DocumentWS.sessions[document.id]['participants']=dict()
                DocumentWS.sessions[document.id]['document'] = document
                DocumentWS.sessions[document.id]['last_diffs'] = json_decode(document.last_diffs)
                DocumentWS.sessions[document.id]['comments'] = json_decode(document.comments)
                DocumentWS.sessions[document.id]['settings'] = json_decode(document.settings)
                DocumentWS.sessions[document.id]['contents'] = json_decode(document.contents)
                DocumentWS.sessions[document.id]['metadata'] = json_decode(document.metadata)
                DocumentWS.sessions[document.id]['in_control'] = self.id
            else:
                self.id = max(DocumentWS.sessions[document.id]['participants'])+1
            DocumentWS.sessions[document.id]['participants'][self.id] = self
            response = dict()
            response['type'] = 'welcome'
            self.write_message(response)

            #DocumentWS.send_participant_list(self.document.id)

    def confirm_diff(self, request_id):
        response = dict()
        response['type'] = 'confirm_diff'
        response['request_id'] = request_id
        self.write_message(response)

    def send_document(self):
        response = dict()
        response['type'] = 'document_data'
        response['document'] = dict()
        document = DocumentWS.sessions[self.user_info.document_id]['document']
        response['document']['id']=document.id
        response['document']['version']=document.version
        if document.diff_version < document.version:
            print "!!!diff version issue!!!"
            document.diff_version = document.version
            DocumentWS.sessions[self.user_info.document_id]["last_diffs"] = []
        response['document']['title']=document.title
        response['document']['contents']=DocumentWS.sessions[self.user_info.document_id]['contents']
        response['document']['metadata']=DocumentWS.sessions[self.user_info.document_id]['metadata']
        response['document']['settings']=DocumentWS.sessions[self.user_info.document_id]['settings']
        access_rights =  get_accessrights(AccessRight.objects.filter(document__owner=document.owner))
        response['document']['access_rights'] = access_rights

        #TODO: switch on filtering when choose workflow and have UI for assigning roles to users
        #filtered_comments = filter_comments_by_role(DocumentWS.sessions[self.user_info.document_id]["comments"], access_rights, 'editing', self.user_info)
        response['document']['comments']=DocumentWS.sessions[self.user_info.document_id]["comments"]
        #response['document']['comments'] = filtered_comments
        response['document']['comment_version']=document.comment_version
        response['document']['access_rights'] = get_accessrights(AccessRight.objects.filter(document__owner=document.owner))
        response['document']['owner'] = dict()
        response['document']['owner']['id']=document.owner.id
        response['document']['owner']['name']=document.owner.readable_name
        response['document']['owner']['avatar']=avatar_url(document.owner,80)
        response['document']['owner']['team_members']=[]

        for team_member in document.owner.leader.all():
            tm_object = dict()
            tm_object['id'] = team_member.member.id
            tm_object['name'] = team_member.member.readable_name
            tm_object['avatar'] = avatar_url(team_member.member,80)
            response['document']['owner']['team_members'].append(tm_object)
        response['document_values'] = dict()
        response['document_values']['is_owner']=self.user_info.is_owner
        response['document_values']['rights'] = self.user_info.access_rights
        if document.version > document.diff_version:
            print "!!!diff version issue!!!"
            document.diff_version = document.version
            DocumentWS.sessions[self.user_info.document_id]["last_diffs"] = []
        elif document.diff_version > document.version:
            needed_diffs = document.diff_version - document.version
            response['document_values']['last_diffs'] = DocumentWS.sessions[self.user_info.document_id]["last_diffs"][-needed_diffs:]
        else:
            response['document_values']['last_diffs'] = []
        if self.user_info.is_new:
            response['document_values']['is_new'] = True
        if not self.user_info.is_owner:
            response['user']=dict()
            response['user']['id']=self.user_info.user.id
            response['user']['name']=self.user_info.user.readable_name
            response['user']['avatar']=avatar_url(self.user_info.user,80)
        if DocumentWS.sessions[self.user_info.document_id]['in_control'] == self.id:
            response['document_values']['control']=True
        response['document_values']['session_id']= self.id
        self.write_message(response)

    def on_message(self, message):
        if not self.user_info.document_id in DocumentWS.sessions:
            print "receiving message for closed document"
            return
        parsed = json_decode(message)
        print parsed["type"]
        if parsed["type"]=='get_document':
            self.send_document()
        elif parsed["type"]=='participant_update':
            self.handle_participant_update()
        elif parsed["type"]=='chat':
            self.handle_chat(parsed)
        elif parsed["type"]=='check_diff_version':
            self.check_diff_version(parsed)
        elif parsed["type"]=='update_document' and self.can_update_document():
            self.handle_document_update(parsed)
        elif parsed["type"]=='update_title' and self.can_update_document():
            self.handle_title_update(parsed)
        elif parsed["type"]=='setting_change' and self.can_update_document():
            self.handle_settings_change(message, parsed)
        elif parsed["type"]=='diff' and self.can_update_document():
            self.handle_diff(message, parsed)

    def update_document(self, changes):
        document = DocumentWS.sessions[self.user_info.document_id]['document']
        if changes["version"] > document.diff_version:
            # The version number is too high. Possibly due to server restart.
            # Do not accept it, and send a document instead.
            self.send_document()
            return
        else:
            # The saved version does not contain all accepted diffs, so we keep the remaining ones + 1000
            remaining_diffs = 1000 + document.diff_version - changes["version"]
            DocumentWS.sessions[self.user_info.document_id]["last_diffs"] = DocumentWS.sessions[self.user_info.document_id]["last_diffs"][-remaining_diffs:]
        DocumentWS.sessions[self.user_info.document_id]["contents"] = changes["contents"]
        DocumentWS.sessions[self.user_info.document_id]["metadata"] = changes["metadata"]
        document.version = changes["version"]

    def update_title(self, title):
        document = DocumentWS.sessions[self.user_info.document_id]['document']
        document.title = title

    def handle_participant_update(self):
        DocumentWS.send_participant_list(self.user_info.document_id)

    def handle_document_update(self, parsed):
        self.update_document(parsed["document"])
        DocumentWS.save_document(self.user_info.document_id)
        message = {
            "type": 'check_hash',
            "diff_version": parsed["document"]["version"],
            "hash": parsed["document"]["hash"]
        }
        DocumentWS.send_updates(message, self.user_info.document_id, self.id)

    def handle_title_update(self, parsed):
        self.update_title(parsed["title"])
        DocumentWS.save_document(self.user_info.document_id)

    def handle_chat(self, parsed):
        chat = {
            "id": str(uuid.uuid4()),
            "body": parsed['body'],
            "from": self.user.id,
            "type": 'chat'
            }
        DocumentWS.send_updates(chat, self.user_info.document_id)

    def handle_settings_change(self, message, parsed):
        if self.user_info.document_id in DocumentWS.sessions:
            DocumentWS.sessions[self.user_info.document_id]['settings'][parsed['variable']] = parsed['value']
            DocumentWS.send_updates(message, self.user_info.document_id, self.id)

    def handle_diff(self, message, parsed):
        if self.user_info.document_id in DocumentWS.sessions:
            document = DocumentWS.sessions[self.user_info.document_id]["document"]
            if parsed["diff_version"] == document.diff_version and parsed["comment_version"] == document.comment_version:
                DocumentWS.sessions[self.user_info.document_id]["last_diffs"].extend(parsed["diff"])
                document.diff_version += len(parsed["diff"])
                for cd in parsed["comments"]:
                    id = str(cd["id"])
                    if cd["type"] == "create":
                        del cd["type"]
                        DocumentWS.sessions[self.user_info.document_id]["comments"][id] = cd
                    elif cd["type"] == "delete":
                        del DocumentWS.sessions[self.user_info.document_id]["comments"][id]
                    elif cd["type"] == "update":
                        DocumentWS.sessions[self.user_info.document_id]["comments"][id]["comment"] = cd["comment"]
                        if "review:isMajor" in cd:
                            DocumentWS.sessions[self.user_info.document_id]["comments"][id]["review:isMajor"] = cd["review:isMajor"]
                    elif cd["type"] == "add_answer":
                        comment_id = str(cd["commentId"])
                        if not "answers" in DocumentWS.sessions[self.user_info.document_id]["comments"][comment_id]:
                            DocumentWS.sessions[self.user_info.document_id]["comments"][comment_id]["answers"] = []
                        del cd["type"]
                        DocumentWS.sessions[self.user_info.document_id]["comments"][comment_id]["answers"].append(cd)
                    elif cd["type"] == "delete_answer":
                        comment_id = str(cd["commentId"])
                        for answer in DocumentWS.sessions[self.user_info.document_id]["comments"][comment_id]["answers"]:
                            if answer["id"] == cd["id"]:
                                DocumentWS.sessions[self.user_info.document_id]["comments"][comment_id]["answers"].remove(answer)
                    elif cd["type"] == "update_answer":
                        comment_id = str(cd["commentId"])
                        for answer in DocumentWS.sessions[self.user_info.document_id]["comments"][comment_id]["answers"]:
                            if answer["id"] == cd["id"]:
                                answer["answer"] = cd["answer"]
                    document.comment_version += 1
                self.confirm_diff(parsed["request_id"])
                DocumentWS.send_updates(message, self.user_info.document_id, self.id)
            elif parsed["diff_version"] != document.diff_version:
                document_session = DocumentWS.sessions[self.user_info.document_id]
                if parsed["diff_version"] < (document_session["document"].diff_version - len(document_session["last_diffs"])):
                    print "unfixable"
                    # Client has a version that is too old
                    self.send_document()
                elif parsed["diff_version"] < document_session["document"].diff_version:
                    print "can fix it"
                    number_requested_diffs = document_session["document"].diff_version - parsed["diff_version"]
                    response = {
                        "type": "diff",
                        "diff_version": parsed["diff_version"],
                        "diff": document_session["last_diffs"][-number_requested_diffs:],
                        "reject_request_id": parsed["request_id"],
                        }
                    self.write_message(response)
                else:
                    print "unfixable"
                    # Client has a version that is too old
                    self.send_document()
            else:
                print "comment_version incorrect!"
                print parsed["comment_version"]
                print document.comment_version

    def check_diff_version(self, parsed):
        document_session = DocumentWS.sessions[self.user_info.document_id]
        if parsed["diff_version"] == document_session["document"].diff_version:
            response = {
                "type": "confirm_diff_version",
                "diff_version": parsed["diff_version"],
            }
            self.write_message(response)
            return
        elif parsed["diff_version"] + len(document_session["last_diffs"]) >= document_session["document"].diff_version:
            number_requested_diffs = document_session["document"].diff_version - parsed["diff_version"]
            response = {
                "type": "diff",
                "diff_version": parsed["diff_version"],
                "diff": document_session["last_diffs"][-number_requested_diffs:],
            }
            self.write_message(response)
            return
        else:
            print "unfixable"
            # Client has a version that is too old
            self.send_document()
            return

    def can_update_document(self):
        return self.user_info.access_rights == 'w' or self.user_info.access_rights == 'a'

    def on_close(self):
        print "Websocket closing"
        if hasattr(self, 'document_id') and self.user_info.document_id in DocumentWS.sessions and self.id in DocumentWS.sessions[self.user_info.document_id]['participants']:
            del DocumentWS.sessions[self.user_info.document_id]['participants'][self.id]
            if DocumentWS.sessions[self.user_info.document_id]['in_control']==self.id:
                if len(DocumentWS.sessions[self.user_info.document_id]['participants'].keys()) > 0:
                    message = {
                        "type": 'take_control'
                        }
                    new_controller = DocumentWS.sessions[self.user_info.document_id]['participants'][min(DocumentWS.sessions[self.user_info.document_id]['participants'])]
                    DocumentWS.sessions[self.user_info.document_id]['in_control'] = new_controller.id
                    new_controller.write_message(message)
                    DocumentWS.send_participant_list(self.user_info.document_id)
                else:
                    DocumentWS.save_document(self.user_info.document_id)
                    del DocumentWS.sessions[self.user_info.document_id]
                    print "noone left"

    @classmethod
    def send_participant_list(cls, document_id):
        if document_id in DocumentWS.sessions:
            participant_list = []
            for waiter in cls.sessions[document_id]['participants'].keys():
                participant_list.append({
                    'key':waiter,
                    'id':cls.sessions[document_id]['participants'][waiter].user_info.user.id,
                    'name':cls.sessions[document_id]['participants'][waiter].user_info.user.readable_name,
                    'avatar':avatar_url(cls.sessions[document_id]['participants'][waiter].user_info.user,80)
                    })
            message = {
                "participant_list": participant_list,
                "type": 'connections'
                }
            DocumentWS.send_updates(message, document_id)

    @classmethod
    def send_updates(cls, message, document_id, sender_id=None):
        info("sending message to %d waiters", len(cls.sessions[document_id]))
        for waiter in cls.sessions[document_id]['participants'].keys():
            if cls.sessions[document_id]['participants'][waiter].id != sender_id:
                try:
                    cls.sessions[document_id]['participants'][waiter].write_message(message)
                except WebSocketClosedError:
                    error("Error sending message", exc_info=True)

    @classmethod
    def save_document(cls, document_id):
        document = cls.sessions[document_id]['document']
        document.contents = json_encode(DocumentWS.sessions[document_id]['contents'])
        document.metadata = json_encode(DocumentWS.sessions[document_id]['metadata'])
        document.settings = json_encode(DocumentWS.sessions[document_id]['settings'])
        document.last_diffs = json_encode(DocumentWS.sessions[document_id]['last_diffs'])
        document.comments = json_encode(DocumentWS.sessions[document_id]['comments'])
        print "saving document"
        document.save()

    @classmethod
    def save_all_docs(cls):
        for document_id in cls.sessions:
            cls.save_document(document_id)

atexit.register(DocumentWS.save_all_docs)
