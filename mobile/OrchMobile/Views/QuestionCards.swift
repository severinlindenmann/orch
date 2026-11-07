import SwiftUI

struct QuestionCard: View {
    let item: ConvItem
    let conversationId: ConversationID
    var onReply: (Question) -> Void
    var onOpenArtifact: (String) -> Void
    var isStale: Bool = false
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var showOther = false

    var body: some View {
        if let q = item.question {
            VStack(alignment: .leading, spacing: 12) {
                if item.answer != nil {
                    Text("Answered").themeFont(13).foregroundStyle(Theme.muted)
                } else if q.isAllow {
                    Image(systemName: "lock").themeFont(13).foregroundStyle(isStale ? Theme.muted : Theme.warn)
                        .accessibilityLabel("Permission")
                } else {
                    Text("Waiting on you").themeFont(13, .semibold).foregroundStyle(isStale ? Theme.muted : Theme.warn)
                }
                Text(q.message.body.text).themeFont(17).fixedSize(horizontal: false, vertical: true)
                if isStale {
                    Text("This question is no longer open.").themeFont(13).foregroundStyle(Theme.muted)
                } else if let answer = item.answer {
                    answered(q, answer: answer)
                } else if model.sendingAnswers.contains(q.id) || model.queuedAnswers[q.id] != nil {
                    sending(q)
                } else {
                    if let suggested = q.message.body.recommended {
                        Text("Suggested: \(label(q, suggested))").themeFont(13).foregroundStyle(Theme.muted)
                    }
                    if q.message.body.options.isEmpty, let answer = model.pendingAnswers[q.id] {
                        selectedChip(q, answer: answer)
                    } else {
                        options(q)
                    }
                    if let answer = model.pendingAnswers[q.id] {
                        undo(q).id(answer)
                    }
                }
                if item.answer == nil {
                    Text(ChatBuilder.timeText(item.at)).themeFont(13).foregroundStyle(Theme.muted)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                }
            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                .foregroundStyle(isStale ? Theme.muted : Theme.text)
                .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(item.answer != nil || isStale ? Theme.border : .clear))
                .buttonStyle(PressStyle()).accessibilityElement(children: .contain)
                .accessibilityIdentifier("question-\(q.id)")
        }
    }

    private func label(_ q: Question, _ option: String) -> String {
        q.isAllow && option == "No" ? "Don't allow" : q.label(option)
    }

    @ViewBuilder private func options(_ q: Question) -> some View {
        let previews = q.message.body.options.filter { q.previewId(for: $0) != nil }
        if q.message.body.options.isEmpty {
            Button { onReply(q) } label: {
                Label("Reply", systemImage: "arrow.turn.up.left").themeFont(15, .medium)
                    .padding(.horizontal, 16).frame(minHeight: 44)
                    .foregroundStyle(Theme.brand).background(Theme.surface3, in: Capsule())
            }.accessibilityIdentifier("question-reply").disabled(model.pendingAnswers[q.id] != nil)
        } else if q.isAllow {
            VStack(spacing: 12) {
                ForEach(q.message.body.options, id: \.self) { option in
                    optionButton(q, option: option, fullWidth: true)
                }
            }
        } else if previews.count == 1, let option = previews.first, let id = q.previewId(for: option) {
            preview(q, id: id, suggested: q.message.body.recommended == option)
            FlowLayout(spacing: 12) {
                ForEach(q.message.body.options, id: \.self) { value in
                    optionButton(q, option: value, primary: value == option)
                }
            }
        } else if !previews.isEmpty {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible())], alignment: .leading, spacing: 12) {
                ForEach(q.message.body.options, id: \.self) { option in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(previewHeading(option)).themeFont(17, .semibold)
                        if let id = q.previewId(for: option) {
                            preview(q, id: id, suggested: q.message.body.recommended == option)
                        }
                        optionButton(q, option: option, title: "Choose " + previewHeading(option), fullWidth: true)
                    }
                }
            }
        } else {
            FlowLayout(spacing: 12) {
                ForEach(q.message.body.options, id: \.self) { option in optionButton(q, option: option) }
            }
        }
    }

    private func previewHeading(_ option: String) -> String {
        option.hasPrefix("Version ") ? String(option.dropFirst("Version ".count)) : option
    }

    private func optionButton(_ q: Question, option: String, title: String? = nil,
                              fullWidth: Bool = false, primary: Bool = false) -> some View {
        let pending = model.pendingAnswers[q.id]
        return Button { model.chooseAnswer(q, option) } label: {
            HStack(spacing: 6) {
                if pending == option { Image(systemName: "checkmark") }
                Text(title ?? label(q, option)).fixedSize(horizontal: false, vertical: true)
            }.themeFont(15, .medium).padding(.horizontal, 12).padding(.vertical, 10)
                .frame(maxWidth: fullWidth ? .infinity : nil, minHeight: 44)
                .foregroundStyle(primary ? Theme.onBrand : Theme.text)
                .background(primary ? Theme.brand : Theme.surface3, in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(q.message.body.recommended == option ? Theme.brand : .clear))
                .opacity(pending != nil && pending != option ? 0.45 : 1)
        }.disabled(pending != nil).accessibilityLabel(option).accessibilityIdentifier("answer-\(option)")
    }

    private func selectedChip(_ q: Question, answer: String, checked: Bool = true) -> some View {
        HStack(spacing: 8) {
            if checked { Image(systemName: "checkmark") }
            Text(label(q, answer))
        }.themeFont(15).padding(.horizontal, 12).padding(.vertical, 10).frame(minHeight: 44)
            .background(Theme.surface3, in: RoundedRectangle(cornerRadius: 10))
            .accessibilityElement(children: .ignore).accessibilityLabel(answer)
            .accessibilityValue(checked ? "Selected" : "")
    }

    private func answered(_ q: Question, answer: String) -> some View {
        let hasOptions = !q.message.body.options.isEmpty
        return VStack(alignment: .leading, spacing: 8) {
            selectedChip(q, answer: answer)
            if !q.message.body.options.isEmpty {
                Button {
                    withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) { showOther.toggle() }
                } label: {
                    Text(showOther ? "Hide other options" : "Show other options").themeFont(15, .medium)
                        .foregroundStyle(Theme.brand).frame(minHeight: 44).contentShape(Rectangle())
                }.accessibilityIdentifier("question-show-other").accessibilityValue(showOther ? "Expanded" : "Collapsed")
                if showOther {
                    FlowLayout(spacing: 12) {
                        ForEach(q.message.body.options, id: \.self) { option in
                            selectedChip(q, answer: option, checked: option == answer)
                                .foregroundStyle(option == answer ? Theme.text : Theme.muted)
                        }
                    }
                }
            }
            if model.answeredElsewhere.contains(q.id) {
                Text("Already answered on your computer: \(label(q, answer))")
                    .themeFont(13).foregroundStyle(Theme.muted).frame(minHeight: 44, alignment: .leading)
            }
        }.accessibilityElement(children: .contain).accessibilityIdentifier("answered-\(q.id)")
            .accessibilityAction(named: showOther ? "Hide other options" : "Show other options") { if hasOptions { showOther.toggle() } }
    }

    private func sending(_ q: Question) -> some View {
        let queued = model.queuedAnswers[q.id]
        let answer = queued ?? model.pendingAnswers[q.id]
        return VStack(alignment: .leading, spacing: 12) {
            if let answer { selectedChip(q, answer: answer) }
            HStack(spacing: 8) {
                if queued != nil { Image(systemName: "clock") } else { ProgressView().tint(Theme.muted) }
                Text(queued != nil ? "Waiting to send" : "Sending…")
            }.themeFont(13).foregroundStyle(Theme.muted)
        }
    }

    private func undo(_ q: Question) -> some View {
        HStack(spacing: 8) {
            Text("Sent in a moment").themeFont(13).foregroundStyle(Theme.muted)
            AnswerUndoRing(seconds: Double(model.undoDelay.components.seconds) + Double(model.undoDelay.components.attoseconds) / 1e18)
            Spacer(minLength: 0)
            Button { model.undoAnswer(q) } label: {
                Text("Undo").themeFont(15, .medium).foregroundStyle(Theme.brand)
                    .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
            }.accessibilityIdentifier("undo-\(q.id)")
        }
    }

    private func attachment(_ q: Question, id: String) -> TicketSnapshot.Attachment? {
        model.tickets.first { $0.workspace == q.message.from && $0.ticket == (q.message.ticket ?? conversationId.ticket) }?
            .view?.attachments.first { $0.id == id }
    }

    private func preview(_ q: Question, id: String, suggested: Bool) -> some View {
        let artifact = attachment(q, id: id)
        return VStack(alignment: .leading, spacing: 0) {
            Group {
                if let blob = artifact?.blobId, !blob.isEmpty { BlobImage(id: blob) }
                else {
                    Text("Preview").themeFont(15).foregroundStyle(Theme.muted)
                        .frame(maxWidth: .infinity, maxHeight: .infinity).background(Theme.surface3)
                }
            }.frame(height: 160).clipped().accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(artifact?.label ?? "Preview").themeFont(15, .semibold)
                Text("Web page preview").themeFont(13).foregroundStyle(Theme.muted)
                Button { onOpenArtifact(id) } label: {
                    Text("Open ↗").themeFont(13, .semibold).foregroundStyle(Theme.brand)
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).contentShape(Rectangle())
                }.accessibilityLabel("Open \(artifact?.label ?? "preview")").accessibilityIdentifier("question-preview-\(id)")
            }.padding(8)
        }.frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface2).clipShape(RoundedRectangle(cornerRadius: 13))
            .overlay(RoundedRectangle(cornerRadius: 13).stroke(suggested ? Theme.brand : Theme.border))
    }
}

private struct AnswerUndoRing: View {
    let seconds: Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var remaining: CGFloat = 1
    var body: some View {
        Circle().trim(from: 0, to: remaining).stroke(Theme.brand, style: StrokeStyle(lineWidth: 2, lineCap: .round))
            .rotationEffect(.degrees(-90)).frame(width: 16, height: 16).accessibilityHidden(true)
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.linear(duration: max(0, seconds))) { remaining = 0 }
            }
            .onChange(of: reduceMotion) { _, reduced in
                if reduced { var transaction = Transaction(); transaction.disablesAnimations = true
                    withTransaction(transaction) { remaining = 1 }
                }
            }
    }
}

/// Measures each chip at the available width, then wraps without clipping larger text.
struct FlowLayout: Layout {
    var spacing: CGFloat = 12

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(width: proposal.width, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(width: bounds.width, subviews: subviews)
        for (index, rect) in result.frames.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + rect.minX, y: bounds.minY + rect.minY),
                                 anchor: .topLeading, proposal: ProposedViewSize(rect.size))
        }
    }

    private func arrange(width: CGFloat?, subviews: Subviews) -> (size: CGSize, frames: [CGRect]) {
        let limit = width.flatMap { $0.isFinite ? max(0, $0) : nil } ?? .greatestFiniteMagnitude
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, usedWidth: CGFloat = 0
        var frames: [CGRect] = []
        for view in subviews {
            let ideal = view.sizeThatFits(.unspecified)
            let size = view.sizeThatFits(ProposedViewSize(width: min(ideal.width, limit), height: nil))
            if x > 0 && x + size.width > limit { x = 0; y += rowHeight + spacing; rowHeight = 0 }
            frames.append(CGRect(x: x, y: y, width: size.width, height: size.height))
            usedWidth = max(usedWidth, x + size.width); rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
        }
        return (CGSize(width: width.map { $0.isFinite ? $0 : usedWidth } ?? usedWidth, height: y + rowHeight), frames)
    }
}
