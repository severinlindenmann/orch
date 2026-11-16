import Foundation

/// "Question taken back" (contracts/relay-api.md; vectors/taken-back-v1.json `phone`). Pure rules.
enum TakenBackRules {
    /// Ids of questions that must leave every list: the workspace that asked sent a `taken_back` text with
    /// `reply_to` = the question, or the relay refused this phone's answer with `409 taken_back` (`refused`).
    /// A text from another sender, from a phone, or for an unknown id closes nothing.
    static func closedIds(questions: [Question], messages: [PhoneMessage], refused: Set<String> = []) -> Set<String> {
        var takenBack = Set<String>()
        for m in messages where !m.fromPhone && m.message.body.isTakenBack {
            if let q = m.message.replyTo { takenBack.insert("\(m.message.from)|\(q)") }
        }
        var closed = Set<String>()
        for q in questions where refused.contains(q.id) || takenBack.contains("\(q.message.from)|\(q.id)") { closed.insert(q.id) }
        return closed
    }

    /// The questions that are still open for the person.
    static func open(_ questions: [Question], messages: [PhoneMessage], refused: Set<String> = []) -> [Question] {
        let closed = closedIds(questions: questions, messages: messages, refused: refused)
        return closed.isEmpty ? questions : questions.filter { !closed.contains($0.id) }
    }
}
