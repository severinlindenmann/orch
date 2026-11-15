import SwiftUI
import UIKit

// The Review stack screens (P4): the row on Chats, the stack of cards, the swipe. Rules live in ReviewStackRules (P3).

/// The "N things to review" rows at the top of Chats, one per workspace that has cards waiting.
struct ReviewStackRows: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let _ = model.revision
        let pending = Set(model.outbox.items.compactMap { $0.verdict != nil ? $0.questionMessageId : nil })
        let spaces = model.workspaceSummaries
        ForEach(spaces) { summary in
            let items = ReviewStackRules.stack(questions: model.questions, answers: model.answers, pending: pending,
                                               later: LaterStore().ids(workspace: summary.id), workspace: summary.id)
            if !items.isEmpty {
                NavigationLink(value: ChatRoute.review(workspace: summary.id)) {
                    HStack(spacing: 12) {
                        Image(systemName: "rectangle.stack").themeFont(20).foregroundStyle(Theme.warn).frame(width: 28).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("\(items.count) \(items.count == 1 ? "thing" : "things") to review").themeFont(17, .semibold).foregroundStyle(Theme.warn)
                            Text(ReviewStackRules.countsText(items)).themeFont(13).foregroundStyle(Theme.muted).lineLimit(2)
                                .accessibilityIdentifier("review-row-counts")
                        }
                        Spacer(minLength: 8)
                        Text("Review").themeFont(14, .semibold).foregroundStyle(Theme.onBrand)
                            .padding(.horizontal, 14).frame(minHeight: 32)
                            .background(Theme.warn, in: Capsule())
                    }.padding(.horizontal, 16).padding(.vertical, 14).frame(minHeight: 44).contentShape(Rectangle())
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(Theme.warn.opacity(0.5)))
                }.buttonStyle(PressStyle()).foregroundStyle(Theme.text)
                    .accessibilityIdentifier("review-stack-row")
                    .accessibilityLabel("\(items.count) \(items.count == 1 ? "thing" : "things") to review. \(ReviewStackRules.countsText(items))")
            }
        }
    }
}

/// What one swipe does, with the words on its stamp.
private struct SwipeAction {
    let direction: SwipeDirection
    let stamp: String
    let color: Color
}

@MainActor
struct ReviewStackView: View {
    let workspaceId: String
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var later: [String] = []
    @State private var focus: String?
    @State private var reopened: Set<String> = []
    @State private var picked: [String: String] = [:]
    @State private var drafts: [String: String] = [:]
    @State private var pins: [String: PinStore] = [:]
    @State private var history: [(id: String, later: Bool)] = []
    @State private var offset: CGSize = .zero
    @State private var dragStart: Date?
    @State private var crossed = false
    @State private var ignoreDrag = false
    @State private var cancelled = false
    @State private var flyOut = false
    @State private var showComment = false
    @State private var commentAbout: String?
    @State private var showOverview = false
    @State private var viewing: ReviewItem?
    @State private var toast: String?
    private let store = LaterStore()

    private var pendingIds: Set<String> {
        Set(model.outbox.items.compactMap { $0.verdict != nil ? $0.questionMessageId : nil })
    }
    private var items: [ReviewItem] {
        ReviewStackRules.stack(questions: model.questions, answers: model.answers, pending: pendingIds.subtracting(reopened), later: later, workspace: workspaceId)
    }
    /// Answered on this phone (or on the computer): everything that is a stack card and not waiting.
    private var answered: [ReviewItem] {
        let waiting = Set(items.map(\.id))
        return model.questionLog.values.filter { $0.message.from == workspaceId && !waiting.contains($0.id) && (model.answers[$0.id] != nil || pendingIds.contains($0.id)) }
            .sorted { $0.message.createdAt < $1.message.createdAt }.compactMap(ReviewStackRules.item(for:))
    }
    private var current: ReviewItem? { items.first { $0.id == focus } ?? items.first }
    private func store(for id: String) -> PinStore { pins[id] ?? { let s = PinStore(); pins[id] = s; return s }() }

    var body: some View {
        let _ = model.revision
        VStack(spacing: 0) {
            topBar
            if let item = current {
                GeometryReader { geo in
                    card(item, size: geo.size)
                }.padding(.horizontal, 16).padding(.top, 8)
                buttons(item)
            } else {
                allDone
            }
        }
        .background(Theme.bg.ignoresSafeArea())
        .foregroundStyle(Theme.text)
        .navigationTitle("Review").navigationBarTitleDisplayMode(.inline)
        .overlay(alignment: .bottom) {
            if let toast {
                Text(toast).themeFont(15, .semibold).padding(.horizontal, 16).padding(.vertical, 10)
                    .background(Theme.surface3, in: Capsule()).padding(.bottom, 90)
                    .accessibilityIdentifier("review-toast").transition(.opacity)
            }
        }
        .sheet(isPresented: $showComment) {
            if let item = current {
                ReviewCommentSheet(item: item, about: $commentAbout, text: Binding(get: { drafts[item.id] ?? "" }, set: { drafts[item.id] = $0 }),
                                   pins: store(for: item.id)) { word, pick in
                    send(item, word, picked: pick, note: note(for: item))
                }
            }
        }
        .sheet(isPresented: $showOverview) {
            ReviewOverview(waiting: items, answered: answered, later: Set(later), workspace: workspaceId,
                           onJump: { id in focus = id; showOverview = false },
                           onChange: { id in reopened.insert(id); focus = id; showOverview = false })
        }
        .fullScreenCover(item: $viewing) { item in
            ReviewViewer(item: item, pins: store(for: item.id), picked: picked[item.id])
        }
        .onAppear {
            later = store.ids(workspace: workspaceId)
            if let f = model.focusedQuestion, items.contains(where: { $0.id == f }) { focus = f; model.focusedQuestion = nil }
        }
        .task(id: model.revision) { store.prune(keeping: Set(model.questionLog.keys), workspace: workspaceId); later = store.ids(workspace: workspaceId) }
    }

    // MARK: Top bar

    private var topBar: some View {
        HStack(spacing: 10) {
            Text("\(answered.count) answered · \(items.count) waiting").themeFont(14, .semibold).foregroundStyle(Theme.muted)
                .accessibilityIdentifier("review-progress")
            Spacer()
            Button { showOverview = true } label: { Text("All").themeFont(15, .semibold).padding(.horizontal, 14).frame(minHeight: 44) }
                .accessibilityIdentifier("review-all").accessibilityLabel("All cards")
            Button { undo() } label: { Text("Undo").themeFont(15, .semibold).padding(.horizontal, 14).frame(minHeight: 44) }
                .disabled(!canUndo).opacity(canUndo ? 1 : 0.4).accessibilityIdentifier("review-undo")
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.brand).padding(.horizontal, 16).padding(.top, 4)
    }

    private var canUndo: Bool {
        guard let last = history.last else { return false }
        return last.later || model.verdictItem(for: last.id)?.canChangeVerdict == true
    }

    private func undo() {
        guard let last = history.popLast() else { return }
        if last.later { store.remove(last.id, workspace: workspaceId); later = store.ids(workspace: workspaceId) }
        else { model.undoVerdict(last.id) }
        focus = last.id
    }

    // MARK: Card

    private func actions(_ item: ReviewItem) -> [SwipeDirection: SwipeAction] {
        let pick = picked[item.id]
        let ok: String
        switch ReviewStackRules.okOutcome(item, picked: pick) {
        case .allowed: ok = item.isChoice ? "Use \(pick ?? "")" : (item.card.okLabel ?? "OK")
        case .pickFirst: ok = "Pick one first"
        case .needsSignature: ok = "Needs your signature"
        }
        let no = item.kind == .draft || item.kind == .plan ? "Don't do" : (item.isChoice ? "None of these" : "Send back")
        return [.right: SwipeAction(direction: .right, stamp: ok, color: Theme.brand),
                .left: SwipeAction(direction: .left, stamp: no, color: Theme.danger),
                .down: SwipeAction(direction: .down, stamp: "Comment", color: Theme.purple),
                .up: SwipeAction(direction: .up, stamp: "Later", color: Theme.warn)]
    }

    private func card(_ item: ReviewItem, size: CGSize) -> some View {
        let dir = ReviewStackRules.direction(dx: offset.width, dy: offset.height)
        let dist = hypot(offset.width, offset.height)
        let stamp = dist > 24 ? actions(item)[dir] : nil
        let tilt = reduceMotion ? 0 : Double(offset.width / max(size.width, 1)) * 10
        return ReviewCardView(item: item, picked: Binding(get: { picked[item.id] }, set: { picked[item.id] = $0 }),
                              state: stateText(for: item), onOpen: { viewing = item })
            .overlay(alignment: .top) {
                if let stamp {
                    Text(stamp.stamp).themeFont(22, .heavy).foregroundStyle(stamp.color).padding(.horizontal, 14).padding(.vertical, 6)
                        .overlay(RoundedRectangle(cornerRadius: Theme.Radius.s, style: .continuous).stroke(stamp.color, lineWidth: 3))
                        .background(Theme.bg.opacity(0.8), in: RoundedRectangle(cornerRadius: Theme.Radius.s, style: .continuous))
                        .rotationEffect(.degrees(dir == .right ? -8 : dir == .left ? 8 : 0)).padding(.top, 18)
                        .opacity(min(1, Double(dist) / 80)).accessibilityIdentifier("review-stamp").accessibilityLabel(stamp.stamp)
                        .allowsHitTesting(false)
                }
            }
            .id(item.id)
            .offset(reduceMotion ? .zero : offset).rotationEffect(.degrees(tilt))
            .opacity(flyOut ? 0 : 1)
            .highPriorityGesture(drag(item, size: size))
            .simultaneousGesture(MagnifyGesture().onChanged { _ in cancelled = true })   // a second finger cancels the swipe
            .accessibilityElement(children: .contain)
            .accessibilityAction(named: "Approve") { commit(item, .right) }
            .accessibilityAction(named: "Don't do") { commit(item, .left) }
            .accessibilityAction(named: "Comment") { commit(item, .down) }
            .accessibilityAction(named: "Later") { commit(item, .up) }
            .accessibilityIdentifier("review-card")
    }

    private func drag(_ item: ReviewItem, size: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 8, coordinateSpace: .global)
            .onChanged { v in
                if dragStart == nil {
                    dragStart = Date(); cancelled = false
                    ignoreDrag = ReviewStackRules.startsAtLeftEdge(x: v.startLocation.x)   // the system back swipe owns the edge
                }
                guard !ignoreDrag, !cancelled else { offset = .zero; return }
                offset = v.translation
                let now = ReviewStackRules.goes(dx: v.translation.width, dy: v.translation.height, speed: 0, size: size) != nil
                if now != crossed { crossed = now; if now { UISelectionFeedbackGenerator().selectionChanged() } }
            }
            .onEnded { v in
                defer { dragStart = nil; crossed = false; ignoreDrag = false }
                let t = max(Date().timeIntervalSince(dragStart ?? Date()), 0.01)
                let speed = hypot(v.translation.width, v.translation.height) / CGFloat(t)
                guard !ignoreDrag, !cancelled,
                      let dir = ReviewStackRules.goes(dx: v.translation.width, dy: v.translation.height, speed: speed, size: size) else {
                    withAnimation(reduceMotion ? nil : .spring(response: 0.35, dampingFraction: 0.7)) { offset = .zero }
                    return
                }
                commit(item, dir)
            }
    }

    // MARK: Actions

    private func note(for item: ReviewItem) -> ReviewVerdict.Note? {
        let text = (drafts[item.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let ps = store(for: item.id).pins.map { ReviewVerdict.Pin(n: $0.n, on: nil, x: $0.place.x, y: $0.place.y, text: $0.text.isEmpty ? nil : $0.text) }
        if text.isEmpty && ps.isEmpty { return nil }
        return ReviewVerdict.Note(changes: nil, words: text.isEmpty ? nil : .init(text: text), pins: ps.isEmpty ? nil : ps)
    }

    private func reset() { withAnimation(reduceMotion ? nil : .spring(response: 0.35, dampingFraction: 0.7)) { offset = .zero } }

    private func say(_ text: String) {
        withAnimation { toast = text }
        Task { try? await Task.sleep(for: .seconds(2.2)); withAnimation { toast = nil } }
    }

    private func commit(_ item: ReviewItem, _ dir: SwipeDirection) {
        switch dir {
        case .right:
            switch ReviewStackRules.okOutcome(item, picked: picked[item.id]) {
            case .needsSignature: UINotificationFeedbackGenerator().notificationOccurred(.warning); say(ReviewStackRules.needsSignatureText + "."); reset()
            case .pickFirst: UINotificationFeedbackGenerator().notificationOccurred(.warning); say("Pick one first."); reset()
            case .allowed: send(item, .ok, picked: picked[item.id], note: nil)
            }
        case .left:
            send(item, .no, picked: nil, note: nil)
        case .down:
            reset(); commentAbout = picked[item.id]; showComment = true
        case .up:
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            store.push(item.id, workspace: workspaceId); later = store.ids(workspace: workspaceId); history.append((item.id, true)); focus = nil
            advance()
        }
    }

    private func send(_ item: ReviewItem, _ word: ReviewVerdict.Word, picked pick: String?, note: ReviewVerdict.Note?) {
        guard !flyOut else { return }
        showComment = false
        Task { @MainActor in
            do {
                if let digest = item.digest {
                    guard let v = ReviewStackRules.verdict(item, word, picked: pick, note: note) else { return }
                    _ = digest
                    try await model.submitVerdict(item, v)
                } else if let legacy = word == .ok ? ReviewStackRules.legacyAnswer(item, picked: pick) : (item.kind == .check ? "changes" : nil) {
                    await model.answer(item.question, with: legacy)
                } else { say("This needs the computer."); reset(); return }
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                history.append((item.id, false)); reopened.remove(item.id); focus = nil
                advance()
            } catch Outbox.VerdictProblem.needsSignature {
                say(ReviewStackRules.needsSignatureText + "."); reset()
            } catch Outbox.VerdictProblem.alreadySent {
                say("Already sent. It can't be changed."); reset()
            } catch { say("Could not use this answer."); reset() }
        }
    }

    private func advance() {
        if reduceMotion { withAnimation(.easeInOut(duration: 0.2)) { flyOut = true } }
        else { withAnimation(.easeIn(duration: 0.18)) { flyOut = true; offset = CGSize(width: offset.width * 3, height: offset.height * 3) } }
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(reduceMotion ? 200 : 180))
            offset = .zero; flyOut = false
        }
    }

    // MARK: Pieces

    private func stateText(for item: ReviewItem) -> String? {
        guard reopened.contains(item.id) || model.verdictItem(for: item.id) != nil else { return nil }
        let r = ReviewStackRules.result(for: item.id, workspace: workspaceId, in: model.messages)
        return ReviewStateText.text(ReviewStackRules.state(item: model.verdictItem(for: item.id), result: r))
    }

    private func buttons(_ item: ReviewItem) -> some View {
        HStack(spacing: 14) {
            roundButton("xmark", "Don't do", id: "review-no", color: Theme.danger) { commit(item, .left) }
            roundButton("mic.fill", "Comment", id: "review-comment", color: Theme.purple) { commit(item, .down) }
            roundButton("checkmark", "Approve", id: "review-ok", color: Theme.brand) { commit(item, .right) }
        }.frame(maxWidth: .infinity).padding(.top, 8).overlay(alignment: .trailing) {
            Button { commit(item, .up) } label: { Text("Later").themeFont(14, .semibold).frame(minWidth: 44, minHeight: 44) }
                .foregroundStyle(Theme.warn).accessibilityIdentifier("review-later").padding(.trailing, 20)
        }.padding(.bottom, 10)
    }

    private func roundButton(_ icon: String, _ label: String, id: String, color: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon).themeFont(22, .bold).foregroundStyle(color).frame(width: 60, height: 60)
                .background(Theme.surface2, in: Circle()).overlay(Circle().stroke(color.opacity(0.6)))
        }.buttonStyle(PressStyle()).accessibilityLabel(label).accessibilityIdentifier(id)
    }

    private var allDone: some View {
        VStack(spacing: 14) {
            Spacer()
            Image(systemName: "checkmark.circle").themeFont(48).foregroundStyle(Theme.brand).accessibilityHidden(true)
            Text("You've answered everything in this review.").themeFont(20, .semibold).multilineTextAlignment(.center)
                .accessibilityIdentifier("review-done")
            Text(tally).themeFont(15).foregroundStyle(Theme.muted).accessibilityIdentifier("review-tally")
            Button("Back to chats") { dismiss() }.buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("review-back")
            Spacer()
        }.padding(24).frame(maxWidth: .infinity)
    }

    private var tally: String {
        var ok = 0, no = 0, talk = 0
        for q in answered {
            switch model.verdictItem(for: q.id)?.verdict?.verdict { case .ok?: ok += 1; case .no?: no += 1; case .talk?: talk += 1; default: break }
        }
        let parts = [(ok, "approved"), (talk, "sent back"), (no, "not done")].filter { $0.0 > 0 }.map { "\($0.0) \($0.1)" }
        return parts.isEmpty ? "\(answered.count) answered" : parts.joined(separator: " · ")
    }
}

/// Plain words of a verdict state (the card chip and the overview).
enum ReviewStateText {
    static func text(_ s: VerdictState?) -> String? {
        switch s {
        case nil: nil
        case .savedOnPhone?: "Saved on this phone"
        case .sent?: "Sent"
        case .received?: "Received"
        case .changed?: "Changed, look again"
        case .refused(let reason)?: "Couldn't use it: " + ReviewStackRules.refusedText(reason)
        case .decided?: "Decided on the computer"
        case .failed?: "Couldn't use it"
        }
    }
}
