/*
Functions related to the editing and sharing of comments.
based on https://github.com/ProseMirror/website/blob/master/src/client/collab/comment.js
*/
import {eventMixin} from "prosemirror/dist/util/event"
import {Transform} from "prosemirror/dist/transform"
import {Pos} from "prosemirror/dist/model"
import {CommentMark} from "../schema"
import {UpdateScheduler} from "prosemirror/dist/ui/update"

class Comment {
    constructor(id, user, userName, userAvatar, date, comment, answers, isMajor) {
        this.id = id
        this.user = user
        this.userName = userName
        this.userAvatar = userAvatar
        this.date = date
        this.comment = comment
        this.answers = answers
        this['review:isMajor'] = isMajor
    }
}

export class ModCommentStore {
    constructor(mod, version) {
        mod.store = this
        this.mod = mod
        this.comments = Object.create(null)
        this.version = version
        this.unsent = []
    }

    // Add a new comment to the comment database both remotely and locally.
    addComment(user, userName, userAvatar, date, comment, answers, isMajor) {
        let id = randomID()
        this.addLocalComment(id, user, userName, userAvatar, date, comment, answers, isMajor)
        this.unsent.push({
            type: "create",
            id: id
        })
        this.mod.editor.pm.execCommand('comment:set', [id])
        this.signal("mustSend")
        return id
    }

    addLocalComment(id, user, userName, userAvatar, date, comment, answers, isMajor) {
        if (!this.comments[id]) {
            this.comments[id] = new Comment(id, user, userName, userAvatar, date, comment, answers, isMajor)
        }
        //this.updateDisplay(true)
    }

    updateComment(id, comment, commentIsMajor) {
        this.updateLocalComment(id, comment, commentIsMajor)
        this.unsent.push({
            type: "update",
            id: id
        })
        this.signal("mustSend")
    }

    updateLocalComment(id, comment, commentIsMajor) {
        if (this.comments[id]) {
            this.comments[id].comment = comment
            this.comments[id]['review:isMajor'] = commentIsMajor
        }
        this.updateDisplay(true)
    }

    removeCommentMarks(id) {
        this.mod.editor.pm.doc.inlineNodesBetween(false, false, ({
            marks
        }, path, start, end) => {
            for (let mark of marks) {
                if (mark.type.name === 'comment' && parseInt(mark.attrs.id) === id) {
                    this.mod.editor.pm.apply(
                        this.mod.editor.pm.tr.removeMark(new Pos(path, start), new Pos(path, end), CommentMark.type)
                    )
                }
            }
        })
    }

    deleteLocalComment(id) {
        let found = this.comments[id]
        if (found) {
            delete this.comments[id]
            return true
        }
        this.updateDisplay(true)
    }

    deleteComment(id) {
        if (this.deleteLocalComment(id)) {
            this.unsent.push({
                type: "delete",
                id: id
            })
            this.removeCommentMarks(id)
            this.signal("mustSend")
        }
    }

    addLocalAnswer(id, answer) {
        if (this.comments[id]) {
            if (!this.comments[id].answers) {
                this.comments[id].answers = []
            }
            this.comments[id].answers.push(answer)
        }
        this.updateDisplay(false)
    }

    addAnswer(id, answer) {
        answer.id = randomID()
        this.addLocalAnswer(id, answer)
        this.unsent.push({
            type: "add_answer",
            id: id,
            answerId: answer.id
        })
        this.signal("mustSend")
    }

    deleteLocalAnswer(commentId, answerId) {
        if (this.comments[commentId] && this.comments[commentId].answers) {
            this.comments[commentId].answers = _.reject(this.comments[commentId].answers, function(answer) {
                return answer.id === answerId
            })
        }
        this.updateDisplay(false)
    }

    deleteAnswer(commentId, answerId) {
        this.deleteLocalAnswer(commentId, answerId)
        this.unsent.push({
            type: "delete_answer",
            commentId: commentId,
            answerId: answerId
        })
        this.signal("mustSend")
    }

    updateLocalAnswer(commentId, answerId, answerText) {
        if (this.comments[commentId] && this.comments[commentId].answers) {
            let answer = _.findWhere(this.comments[commentId].answers, {
                id: answerId
            })
            answer.answer = answerText
        }
        this.updateDisplay(false)
    }

    updateAnswer(commentId, answerId, answerText) {
        this.updateLocalAnswer(commentId, answerId, answerText)
        this.unsent.push({
            type: "update_answer",
            commentId: commentId,
            answerId: answerId
        })
        this.signal("mustSend")
    }

    hasUnsentEvents() {
        return this.unsent.length
    }

    unsentEvents() {
        let result = []
        for (let i = 0; i < this.unsent.length; i++) {
            let event = this.unsent[i]
            if (event.type == "delete") {
                result.push({
                    type: "delete",
                    id: event.id
                })
            } else if (event.type == "update") {
                let found = this.comments[event.id]
                if (!found || !found.id) continue
                result.push({
                    type: "update",
                    id: found.id,
                    comment: found.comment,
                    'review:isMajor': found['review:isMajor']
                })
            } else if (event.type == "create") {
                let found = this.comments[event.id]
                if (!found || !found.id) continue
                result.push({
                    type: "create",
                    id: found.id,
                    user: found.user,
                    userName: found.userName,
                    userAvatar: found.userAvatar,
                    date: found.date,
                    comment: found.comment,
                    answers: found.answers,
                    'review:isMajor': found['review:isMajor']
                })
            } else if (event.type == "add_answer") {
                let found = this.comments[event.id]
                if (!found || !found.id || !found.answers) continue
                let foundAnswer = _.findWhere(found.answers, {
                    id: event.answerId
                })
                result.push({
                    type: "add_answer",
                    id: foundAnswer.id,
                    commentId: foundAnswer.commentId,
                    user: foundAnswer.user,
                    userName: foundAnswer.userName,
                    userAvatar: foundAnswer.userAvatar,
                    date: foundAnswer.date,
                    answer: foundAnswer.answer
                })
            } else if (event.type == "delete_answer") {
                result.push({
                    type: "delete_answer",
                    commentId: event.commentId,
                    id: event.answerId
                })
            } else if (event.type == "update_answer") {
                let found = this.comments[event.commentId]
                if (!found || !found.id || !found.answers) continue
                let foundAnswer = _.findWhere(found.answers, {
                    id: event.answerId
                })
                result.push({
                    type: "update_answer",
                    id: foundAnswer.id,
                    commentId: foundAnswer.commentId,
                    answer: foundAnswer.answer
                })
            }
        }
        return result
    }

    eventsSent(n) {
        this.unsent = this.unsent.slice(n)
        this.version += n
    }

    receive(events, version) {
        events.forEach(event => {
            if (event.type == "delete") {
                this.deleteLocalComment(event.id)
            } else if (event.type == "create") {
                this.addLocalComment(event.id, event.user, event.userName, event.userAvatar, event.date, event.comment, event['review:isMajor'])
            } else if (event.type == "update") {
                this.updateLocalComment(event.id, event.comment, event['review:isMajor'])
            } else if (event.type == "add_answer") {
                this.addLocalAnswer(event.commentId, event)
            } else if (event.type == "remove_answer") {
                this.deleteLocalAnswer(event.commentId, event)
            } else if (event.type == "update_answer") {
                this.updateLocalAnswer(event.commentId, event.id, event.answer)
            }
            this.version++
        })

    }

    updateDisplay(waitForFlush) {
        console.log('yuyu')
        let that = this
        if (waitForFlush) {
            let layoutComments = new UpdateScheduler(this.mod.editor.pm, "flush", function() {
                layoutComments.detach()
                console.log('layouting comments')
                that.mod.layout.layoutComments()
            })
        } else {
            that.mod.layout.layoutComments()
        }
    }

    findCommentsAt(pos) {
        let found = [],
            node = this.mod.editor.pm.doc.path(pos.path)

        for (let mark in node.marks) {
            if (mark.type.name === 'comment' && mark.attrs.id in this.comments)
                found.push(this.comments[mark.attrs.id])
        }
        return found
    }
}

eventMixin(ModCommentStore)

function randomID() {
    return Math.floor(Math.random() * 0xffffffff)
}
