import SwiftUI

struct MakeTicketCard: View {
    let question: Question
    let answer: String?
    @Environment(AppModel.self) private var model
    @State private var tapped: String?
    @State private var answeredAt = Date()

    private var pending: String? {
        tapped ?? model.pendingAnswers[question.id] ?? model.queuedAnswers[question.id]
    }
    private var busy: Bool { pending != nil || model.sendingAnswers.contains(question.id) }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 15)) { context in
            content(state(at: context.date))
        }
    }

    private func state(at now: Date) -> MakeTicketRules.CardState {
        let results = model.messages.filter {
            $0.message.from == question.message.from && $0.message.replyTo == question.id && $0.message.body.isProposalResult
        }.sorted { $0.message.createdAt < $1.message.createdAt }.compactMap { $0.message.body.proposalResult }
        return MakeTicketRules.state(answer: answer ?? model.answers[question.id] ?? pending,
                                    answeredAt: model.answerTime(for: question.id) ?? answeredAt,
                                    results: results, now: now,
                                    workspaceLive: model.presence(of: question.message.from, now: now) == .online)
    }

    private func content(_ state: MakeTicketRules.CardState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            switch state {
            case .making: status("Making topic…", spinning: true)
            case .waiting: status("Waiting for \(question.workspaceName)…", spinning: true)
            case .made(let key):
                status("Topic made")
                if let key { DisclosureGroup("Details") { Text(key).themeFont(13) }.themeFont(13) }
            case .failed: status("Couldn't make the topic")
            case .closed(let notNow): status(notNow ? "Not now" : "Already decided")
            case .open:
                Text(question.message.body.text).themeFont(15)
                Text(question.message.body.title ?? "").themeFont(17, .semibold)
                if let date = Self.dateLabel(question.message.body.when) {
                    Text(date).themeFont(13).foregroundStyle(Theme.muted)
                }
                HStack(spacing: 10) {
                    option("make", title: "Make topic", primary: true, id: "make-ticket")
                    option("not_now", title: "Not now", primary: false, id: "make-ticket-not-now")
                }.disabled(busy)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .foregroundStyle(Theme.text)
        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
        .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m).stroke(Theme.border))
        .buttonStyle(PressStyle())
        .accessibilityElement(children: .contain).accessibilityIdentifier("make-ticket-card")
    }

    private func status(_ text: String, spinning: Bool = false) -> some View {
        HStack(spacing: 6) {
            if spinning { ProgressView().controlSize(.small).tint(Theme.muted) }
            Text(text).themeFont(13)
        }.foregroundStyle(Theme.muted)
    }

    private func option(_ value: String, title: String, primary: Bool, id: String) -> some View {
        Button {
            guard !busy else { return }
            answeredAt = Date()
            tapped = value
            Task {
                await model.answer(question, with: value)
                tapped = nil
            }
        } label: {
            HStack(spacing: 6) {
                if pending == value { ProgressView().controlSize(.small).tint(primary ? Theme.onBrand : Theme.text) }
                Text(title).themeFont(15, .semibold)
            }
            .frame(maxWidth: .infinity, minHeight: 48)
            .foregroundStyle(primary ? Theme.onBrand : Theme.text)
            .background(primary ? Theme.brand : .clear, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m).stroke(primary ? .clear : Theme.borderStrong))
        }.accessibilityIdentifier(id)
    }

    static func dateLabel(_ value: String?) -> String? {
        guard let value else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_GB")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        guard let date = formatter.date(from: value), formatter.string(from: date) == value else { return nil }
        formatter.dateFormat = "EEE d MMM"
        return formatter.string(from: date)
    }
}
