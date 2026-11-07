import SwiftUI

/// "Chat archived · Undo" toast, shared by the workspace screen and the Archived list.
struct ArchiveToast: Equatable {
    let id = UUID()
    let text: String
    let undo: (() -> Void)?
    static func == (a: ArchiveToast, b: ArchiveToast) -> Bool { a.id == b.id }
}

struct ArchiveToastBar: View {
    let toast: ArchiveToast
    let dismiss: () -> Void
    var body: some View {
        HStack(spacing: 14) {
            Text(toast.text).themeFont(15)
            Spacer(minLength: 8)
            if let undo = toast.undo {
                Button { undo(); dismiss() } label: {
                    Text("Undo").themeFont(15, .semibold).foregroundStyle(Theme.brand)
                        .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
                }.buttonStyle(PressStyle()).accessibilityIdentifier("archive-undo")
                    .accessibilityHint("Reverses the last archive or move back action.")
            }
        }.foregroundStyle(Theme.text).padding(.horizontal, 16).padding(.vertical, 4)
            .background(Theme.surface3, in: RoundedRectangle(cornerRadius: 14))
            .overlay { RoundedRectangle(cornerRadius: 14).strokeBorder(Theme.border, lineWidth: 1) }
            .shadow(color: Theme.bg.opacity(0.5), radius: 8, y: 4)
            .padding(.horizontal, 16).accessibilityIdentifier("archive-toast")
    }
}

extension View {
    /// Shows the toast near the bottom and hides it after the undo window.
    func archiveToast(_ toast: Binding<ArchiveToast?>, bottom: CGFloat = 12) -> some View {
        overlay(alignment: .bottom) {
            if let t = toast.wrappedValue { ArchiveToastBar(toast: t) { toast.wrappedValue = nil }.padding(.bottom, bottom).transition(.opacity) }
        }.task(id: toast.wrappedValue?.id) {
            guard toast.wrappedValue != nil else { return }
            try? await Task.sleep(for: .seconds(5))
            if !Task.isCancelled { toast.wrappedValue = nil }
        }
    }

    /// Plain confirmation before a chat is erased on this phone (draft 2-phone-archive B).
    func confirmDelete(_ id: Binding<ConversationID?>, onDelete: @escaping (ConversationID) -> Void) -> some View {
        let isGeneral: Bool = { if case .general? = id.wrappedValue { true } else { false } }()
        return confirmationDialog("Delete this chat from your phone?", isPresented: Binding(get: { id.wrappedValue != nil }, set: { if !$0 { id.wrappedValue = nil } }),
                                  titleVisibility: .visible) {
            Button("Delete chat", role: .destructive) { if let c = id.wrappedValue { onDelete(c) }; id.wrappedValue = nil }.accessibilityIdentifier("delete-confirm")
            Button("Cancel", role: .cancel) { id.wrappedValue = nil }
        } message: {
            Text(isGeneral ? "This erases General on this phone. It cannot be undone."
                           : "The messages leave this phone. The ticket and its history stay in your workspace and on the dashboard.")
        }
    }
}

/// Archived chats, per workspace (or all workspaces when `workspaceId` is nil). Move back by swipe, button or context menu.
struct ArchivedView: View {
    @AppStorage("workspaceAliasRevision") private var aliasRevision = 0
    var workspaceId: String?
    @Environment(AppModel.self) private var model
    @State private var deleting: ConversationID?
    @State private var toast: ArchiveToast?

    private var groups: [(summary: WorkspaceSummary, chats: [ArchivedChat])] {
        model.workspaceSummaries.filter { workspaceId == nil || $0.id == workspaceId }
            .map { ($0, model.split($0).archived) }.filter { !$0.1.isEmpty }
    }

    var body: some View {
        let _ = aliasRevision
        List {
            if groups.isEmpty {
                Text("Nothing archived.").themeFont(15).foregroundStyle(Theme.muted).frame(maxWidth: .infinity).padding(.vertical, 40)
                    .listRowBackground(Color.clear).listRowSeparator(.hidden)
            }
            ForEach(groups, id: \.summary.id) { group in
                Section {
                    ForEach(group.chats) { chat in row(chat) }
                } header: {
                    Text(WorkspaceAlias.name(for: group.summary.workspace))
                        .themeFont(13, .semibold).foregroundStyle(Theme.muted).textCase(nil)
                }
            }
        }.listStyle(.insetGrouped).listSectionSpacing(14).scrollContentBackground(.hidden).background(Theme.bg.ignoresSafeArea())
            .navigationTitle("Archived").navigationBarTitleDisplayMode(.inline).toolbar(.visible, for: .navigationBar)
            .confirmDelete($deleting) { id in model.deleteChat(id) }
            .archiveToast($toast).foregroundStyle(Theme.text)
    }

    private func subtitle(_ chat: ArchivedChat) -> String {
        let day = ShellTime.day(chat.lastAt)
        if !chat.byHand { return "Done · archived automatically" }
        return day.isEmpty ? "Archived" : "Archived · last message \(day)"
    }

    @ViewBuilder private func row(_ chat: ArchivedChat) -> some View {
        HStack(spacing: 12) {
            Group {
                if let ticket = chat.id.ticket {
                    NavigationLink(value: ChatRoute.ticket(workspace: chat.workspaceId, ticket: ticket)) { chatLabel(chat) }
                } else {
                    NavigationLink { ChatRoomView(workspaceId: chat.workspaceId).toolbar(.visible, for: .navigationBar) } label: { chatLabel(chat) }
                }
            }.buttonStyle(PressStyle()).frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("archived-\(ReadState.key(chat.id))")
            Button { moveBack(chat) } label: {
                Text("Move back").themeFont(13, .semibold).foregroundStyle(Theme.brand)
                    .multilineTextAlignment(.center).padding(.horizontal, 12)
                    .frame(minWidth: 44, minHeight: 44)
                    .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 10))
                    .overlay { RoundedRectangle(cornerRadius: 10).strokeBorder(Theme.borderStrong, lineWidth: 1) }
                    .contentShape(Rectangle())
            }.buttonStyle(PressStyle()).accessibilityIdentifier("move-back-\(ReadState.key(chat.id))")
                .accessibilityLabel("Move back \(chat.title)")
                .accessibilityHint("Returns this chat to its workspace list.")
        }.listRowInsets(EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 16))
            .listRowBackground(Theme.surface).listRowSeparatorTint(Theme.border)
            .swipeActions(edge: .leading, allowsFullSwipe: true) {
                Button { moveBack(chat) } label: { Label("Move back", systemImage: "tray.and.arrow.up") }.tint(Theme.brand)
            }
            .contextMenu {
                Button { moveBack(chat) } label: { Label("Move back", systemImage: "tray.and.arrow.up") }
                if ArchiveStore.canDelete(chat.status) { Button(role: .destructive) { deleting = chat.id } label: { Label("Delete", systemImage: "trash") } }
            }
    }

    private func chatLabel(_ chat: ArchivedChat) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(chat.title).themeFont(17, .semibold).lineLimit(3).multilineTextAlignment(.leading)
            Text(subtitle(chat)).themeFont(13).foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }.frame(maxWidth: .infinity, minHeight: 56, alignment: .leading).contentShape(Rectangle())
            .accessibilityElement(children: .combine)
    }

    private func moveBack(_ chat: ArchivedChat) {
        model.moveBack(chat.id)
        toast = ArchiveToast(text: "Moved back") { model.archiveChat(chat.id) }
    }
}
