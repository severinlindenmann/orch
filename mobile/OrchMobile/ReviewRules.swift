import Foundation

/// Review controls are scoped to the current ticket snapshot and an unanswered relay question.
enum ReviewRules {
    static func reviewQuestion(ticket: Ticket?, workspaceId: String, ticketId: String,
                               questions: [Question], answers: [String: String]) -> Question? {
        guard let ticket, ticket.status == .review, ticket.workspace == workspaceId, ticket.ticket == ticketId else { return nil }
        return questions.filter {
            $0.message.from == workspaceId && $0.message.ticket == ticketId && $0.isReview && answers[$0.id] == nil
        }.max {
            let a = ConversationRules.date($0.message.createdAt) ?? .distantPast
            let b = ConversationRules.date($1.message.createdAt) ?? .distantPast
            return a == b ? $0.id < $1.id : a < b
        }
    }

    /// These wire option words cannot describe requested changes.
    static func isReservedAnswer(_ text: String) -> Bool {
        ["accept", "changes"].contains(text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
    }
}
