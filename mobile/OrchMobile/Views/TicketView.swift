import SwiftUI

/// One ticket: where things stand, the last result, and a Reply that goes back on the same ticket.
struct TicketView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let ticket: Ticket
    @State private var reply = ""
    @State private var sending = false
    @FocusState private var editing: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 8) {
                    Image(systemName: ticket.symbol).foregroundStyle(tint)
                    Text(ticket.status.title).themeFont(12, .semibold).foregroundStyle(tint)
                    Spacer()
                    Text(ticket.workspaceName).themeFont(12).foregroundStyle(Theme.muted)
                }.accessibilityElement(children: .combine)
                Text(ticket.title).themeFont(22, .semibold).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("ticket-title")
                if ticket.status != .done {
                    Eyebrow(text: "WHERE THINGS STAND")
                    Text(ticket.text).themeFont(14).foregroundStyle(Theme.text)
                } else {
                    Eyebrow(text: ticket.kind == "result" ? "RESULT" : (ticket.kind == "stopped" ? "STOPPED" : "WHAT WENT WRONG"))
                    Text(ticket.text).themeFont(14).foregroundStyle(Theme.text)
                }
                if ticket.question != nil {
                    Button("Answer the question") { dismiss(); if let q = ticket.question { model.openQuestion(messageId: q.id) } }
                        .buttonStyle(PrimaryButtonStyle(muted: false)).accessibilityIdentifier("ticket-answer")
                }
                if ticket.ticket != nil {
                    Eyebrow(text: "REPLY").padding(.top, 8)
                    TextField("Write a reply", text: $reply, axis: .vertical).lineLimit(1...5).focused($editing)
                        .themeFont(14).padding(12).frame(minHeight: 48)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.borderStrong))
                        .accessibilityIdentifier("ticket-reply-field")
                    let canSend = !sending && !reply.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    Button(sending ? "Sending…" : "Reply ↑") {
                        guard canSend, let t = ticket.ticket else { return }
                        sending = true
                        Task {
                            if await model.send(to: ticket.workspace, text: reply, ticket: t) { dismiss() }
                            sending = false
                        }
                    }.buttonStyle(PrimaryButtonStyle(muted: !canSend)).disabled(!canSend)
                        .accessibilityIdentifier("ticket-reply-send")
                }
                ModelMessage()
            }.padding(.horizontal, 23).padding(.vertical, 24)
        }.scrollDismissesKeyboard(.interactively).background(Theme.bg.ignoresSafeArea())
    }

    private var tint: Color {
        switch ticket.status {
        case .needsYou: Theme.warn
        case .working: Theme.muted
        case .done: ticket.kind == "result" ? Theme.brand : Theme.danger
        }
    }
}
