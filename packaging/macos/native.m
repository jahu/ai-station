// Native presentation/bootstrap only. Workloads belong to the existing supervisor.
#import <Cocoa/Cocoa.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <sys/stat.h>
#import <unistd.h>
#import <stdio.h>
#import <string.h>
#import <dispatch/dispatch.h>

static NSString *field(NSDictionary *value, NSString *key, NSString *fallback) {
    id item = value[key];
    return [item isKindOfClass:NSString.class] ? item : fallback;
}

static void answer(NSString *action) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:@{@"action": action} options:0 error:NULL];
    [[NSFileHandle fileHandleWithStandardOutput] writeData:data];
    [[NSFileHandle fileHandleWithStandardOutput] writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
}

static NSImage *stationIcon(void) {
    NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(64, 64)];
    [image lockFocus];
    [[NSColor colorWithSRGBRed:0.10 green:0.11 blue:0.16 alpha:1] setFill];
    [[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(0, 0, 64, 64) xRadius:15 yRadius:15] fill];
    NSBezierPath *spark = [NSBezierPath bezierPath];
    [spark moveToPoint:NSMakePoint(32, 54)];
    [spark lineToPoint:NSMakePoint(38, 38)];
    [spark lineToPoint:NSMakePoint(54, 32)];
    [spark lineToPoint:NSMakePoint(38, 26)];
    [spark lineToPoint:NSMakePoint(32, 10)];
    [spark lineToPoint:NSMakePoint(26, 26)];
    [spark lineToPoint:NSMakePoint(10, 32)];
    [spark lineToPoint:NSMakePoint(26, 38)];
    [spark closePath];
    NSGradient *gradient = [[NSGradient alloc] initWithStartingColor:
        [NSColor colorWithSRGBRed:0.66 green:0.51 blue:1 alpha:1]
        endingColor:[NSColor colorWithSRGBRed:0.30 green:0.85 blue:0.86 alpha:1]];
    [gradient drawInBezierPath:spark angle:-45];
    [image unlockFocus];
    return image;
}

static void prepareUI(NSApplicationActivationPolicy policy) {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:policy];
    NSApp.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    NSApp.applicationIconImage = stationIcon();
    [NSApp activateIgnoringOtherApps:YES];
}

static int showDialog(BOOL running) {
    NSData *input = [[NSFileHandle fileHandleWithStandardInput] readDataOfLength:16385];
    if (input.length > 16384) return 2;
    id request = [NSJSONSerialization JSONObjectWithData:input options:0 error:NULL];
    if (![request isKindOfClass:NSDictionary.class]) return 2;
    prepareUI(NSApplicationActivationPolicyAccessory);
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"AI Station";
    alert.informativeText = field(request, @"text", @"");
    alert.icon = stationIcon();
    alert.alertStyle = [field(request, @"kind", @"") isEqual:@"error"] ? NSAlertStyleWarning : NSAlertStyleInformational;
    if (running) {
        [alert addButtonWithTitle:@"Open AI Station"];
        [alert addButtonWithTitle:@"Run in background"];
        [alert addButtonWithTitle:@"Stop AI Station"];
        alert.buttons[1].keyEquivalent = @"\033";
    } else {
        [alert addButtonWithTitle:field(request, @"ok", @"Continue")];
        if (request[@"cancel"]) {
            [alert addButtonWithTitle:field(request, @"cancel", @"Cancel")];
            alert.buttons[1].keyEquivalent = @"\033";
        }
    }
    NSModalResponse result = [alert runModal];
    if (running) {
        answer(result == NSAlertFirstButtonReturn ? @"open" : result == NSAlertThirdButtonReturn ? @"stop" : @"background");
        return 0;
    }
    answer(result == NSAlertFirstButtonReturn ? @"ok" : @"cancel");
    return result == NSAlertFirstButtonReturn ? 0 : 1;
}

@interface ProgressDelegate : NSObject <NSWindowDelegate>
@property(strong) NSButton *cancelButton;
@property(assign) BOOL canceled;
- (void)cancel:(id)sender;
@end
@implementation ProgressDelegate
- (void)windowWillClose:(NSNotification *)notification { [NSApp terminate:nil]; }
- (void)cancel:(id)sender {
    if (self.canceled || !self.cancelButton.enabled) return;
    self.canceled = YES;
    self.cancelButton.enabled = NO;
    self.cancelButton.title = @"Canceling…";
    answer(@"cancel");
}
@end
static ProgressDelegate *progressDelegate;

static int progressWindow(BOOL smoke, BOOL cancelSmoke) {
    prepareUI(NSApplicationActivationPolicyAccessory);
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 480, 176)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        backing:NSBackingStoreBuffered defer:NO];
    window.title = @"AI Station";
    window.releasedWhenClosed = NO;
    progressDelegate = [ProgressDelegate new];
    window.delegate = progressDelegate;
    NSTextField *heading = [NSTextField labelWithString:@"Your local workstation is starting"];
    heading.font = [NSFont systemFontOfSize:17 weight:NSFontWeightSemibold];
    heading.frame = NSMakeRect(28, 112, 424, 28);
    NSTextField *stage = [NSTextField wrappingLabelWithString:@"Preparing AI Station…"];
    stage.font = [NSFont systemFontOfSize:13];
    stage.textColor = NSColor.secondaryLabelColor;
    stage.frame = NSMakeRect(28, 61, 424, 44);
    NSProgressIndicator *indicator = [[NSProgressIndicator alloc] initWithFrame:NSMakeRect(28, 31, 424, 16)];
    indicator.style = NSProgressIndicatorStyleBar;
    indicator.indeterminate = YES;
    [indicator startAnimation:nil];
    [window.contentView addSubview:heading];
    [window.contentView addSubview:stage];
    [window.contentView addSubview:indicator];
    NSTextField *hint = [NSTextField labelWithString:@"AI Station keeps working if you close this window."];
    hint.font = [NSFont systemFontOfSize:11];
    hint.textColor = NSColor.tertiaryLabelColor;
    hint.frame = NSMakeRect(28, 6, 424, 18);
    [window.contentView addSubview:hint];
    NSButton *cancel = [NSButton buttonWithTitle:@"Cancel" target:progressDelegate action:@selector(cancel:)];
    cancel.frame = NSMakeRect(354, 4, 98, 26);
    cancel.hidden = YES;
    progressDelegate.cancelButton = cancel;
    [window.contentView addSubview:cancel];
    [window center];
    [window makeKeyAndOrderFront:nil];
    if (smoke || cancelSmoke) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            if (cancelSmoke) {
                cancel.hidden = NO;
                cancel.enabled = YES;
                [progressDelegate cancel:cancel];
                if (!progressDelegate.canceled || cancel.enabled) exit(1);
                answer(@"native-backup-progress-cancel-passed");
            } else answer(@"native-ui-smoke-passed");
            [NSApp terminate:nil];
        });
    } else {
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            char buffer[16385];
            while (fgets(buffer, sizeof(buffer), stdin)) {
                @autoreleasepool {
                    size_t length = strlen(buffer);
                    if (!length || buffer[length - 1] != '\n') break;
                    NSData *data = [NSData dataWithBytes:buffer length:length];
                    id value = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
                    if (![value isKindOfClass:NSDictionary.class]) break;
                    NSString *text = field(value, @"stage", @"");
                    NSString *title = field(value, @"heading", @"");
                    if (text.length > 4096 || title.length > 128) break;
                    dispatch_async(dispatch_get_main_queue(), ^{
                        if (value[@"stage"]) stage.stringValue = text;
                        if (value[@"heading"]) heading.stringValue = title;
                        if ([value[@"cancelable"] isKindOfClass:NSNumber.class]) {
                            BOOL allowed = [value[@"cancelable"] boolValue];
                            cancel.hidden = NO;
                            cancel.enabled = allowed && !progressDelegate.canceled;
                            hint.stringValue = allowed ? @"Closing this window keeps the operation running." : @"Finishing safely. Please wait.";
                            hint.frame = NSMakeRect(28, 6, 320, 18);
                        }
                        if ([value[@"done"] isKindOfClass:NSNumber.class] && [value[@"total"] isKindOfClass:NSNumber.class]) {
                            double done = [value[@"done"] doubleValue], total = [value[@"total"] doubleValue];
                            if (total > 0 && total <= 1e12 && done >= 0 && done <= total) {
                                indicator.indeterminate = NO;
                                indicator.minValue = 0;
                                indicator.maxValue = total;
                                indicator.doubleValue = done;
                            }
                        } else if (value[@"total"]) {
                            indicator.indeterminate = YES;
                            [indicator startAnimation:nil];
                        }
                    });
                }
            }
            dispatch_async(dispatch_get_main_queue(), ^{ [NSApp terminate:nil]; });
        });
    }
    [NSApp run];
    return 0;
}

static NSOpenPanel *updatePanel(void) {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.title = @"Install an AI Station update";
    panel.message = @"Choose the AI Station.app you downloaded. Your saved data stays on this Mac.";
    panel.prompt = @"Choose update";
    panel.allowedContentTypes = @[UTTypeApplicationBundle];
    panel.canChooseFiles = YES;
    panel.canChooseDirectories = NO;
    panel.allowsMultipleSelection = NO;
    panel.treatsFilePackagesAsDirectories = NO;
    panel.resolvesAliases = YES;
    return panel;
}

static int updateChooserSmoke(void) {
    prepareUI(NSApplicationActivationPolicyAccessory);
    NSOpenPanel *panel = updatePanel();
    if (panel.allowsMultipleSelection || panel.canChooseDirectories || panel.allowedContentTypes.count != 1) return 1;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{ [panel cancel:nil]; });
    if ([panel runModal] != NSModalResponseCancel) return 1;
    answer(@"native-update-chooser-cancel-passed");
    return 0;
}

static NSOpenPanel *backupPanel(void) {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.title = @"Choose an AI Station backup";
    panel.message = @"Select the complete backup folder. AI Station will check it before changing saved data.";
    panel.prompt = @"Check backup";
    panel.canChooseFiles = NO;
    panel.canChooseDirectories = YES;
    panel.allowsMultipleSelection = NO;
    panel.resolvesAliases = NO;
    return panel;
}

static int backupDialog(BOOL folder, BOOL smoke) {
    prepareUI(NSApplicationActivationPolicyAccessory);
    if (folder || smoke) {
        NSOpenPanel *panel = backupPanel();
        if (smoke) {
            if (panel.canChooseFiles || !panel.canChooseDirectories || panel.allowsMultipleSelection || panel.resolvesAliases) return 1;
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{ [panel cancel:nil]; });
        }
        if ([panel runModal] != NSModalResponseOK) {
            answer(smoke ? @"native-backup-chooser-cancel-passed" : @"cancel");
            return 0;
        }
        NSString *path = panel.URL.path;
        if (!path || path.length > 8192) return 2;
        NSData *data = [NSJSONSerialization dataWithJSONObject:@{@"path":path} options:0 error:NULL];
        [[NSFileHandle fileHandleWithStandardOutput] writeData:data];
        return 0;
    }
    NSData *input = [[NSFileHandle fileHandleWithStandardInput] readDataOfLength:16385];
    if (input.length > 16384) return 2;
    id request = [NSJSONSerialization JSONObjectWithData:input options:0 error:NULL];
    if (![request isKindOfClass:NSDictionary.class]) return 2;
    NSString *pending = field(request, @"pending", @"");
    BOOL restore = [pending isEqual:@"restore"], backup = [pending isEqual:@"backup"];
    if (pending.length && !restore && !backup) return 2;
    BOOL canAbort = [request[@"can_abort"] isKindOfClass:NSNumber.class] && [request[@"can_abort"] boolValue];
    NSAlert *alert = [NSAlert new];
    alert.icon = stationIcon();
    alert.messageText = pending.length ? @"Continue an interrupted operation" : @"Back up your AI Station";
    alert.informativeText = pending.length ? @"Your saved data and recovery records have been kept. Continue the same operation before starting AI Station." : @"Create a complete private backup of your conversations, files, models and accounts, or restore a previous backup. AI Station will stop briefly and reopen afterward.";
    [alert addButtonWithTitle:restore ? @"Continue restore" : backup ? @"Continue backup" : @"Create backup"];
    if (!pending.length || canAbort) [alert addButtonWithTitle:pending.length ? @"Cancel operation" : @"Restore backup…"];
    [alert addButtonWithTitle:@"Close"];
    alert.buttons.lastObject.keyEquivalent = @"\033";
    NSModalResponse choice = [alert runModal];
    if (choice == NSAlertFirstButtonReturn) answer(pending.length ? @"resume" : @"export");
    else if (choice == NSAlertSecondButtonReturn && (!pending.length || canAbort)) answer(pending.length ? @"abort" : @"restore");
    else answer(@"cancel");
    return 0;
}

@interface StationDelegate : NSObject <NSApplicationDelegate, NSMenuItemValidation>
@property(strong) NSTask *launcher;
@property(strong) NSTask *updateTask;
@property(strong) NSURL *resources;
@property(copy) NSString *bootstrapIdentity;
@property(assign) BOOL stopping;
@property(strong) NSMutableArray<NSTask *> *reopenTasks;
@end

@implementation StationDelegate
- (void)showUpdateFailure {
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"AI Station needs your attention";
    alert.informativeText = @"Your saved data and recovery records have been kept. Open AI Station again to continue an interrupted operation, or check the application package and Docker Desktop.";
    alert.icon = stationIcon();
    [alert runModal];
}
- (void)taskFinished:(NSTask *)finished {
    if (self.stopping) {
        if (!self.launcher.running && !self.updateTask.running) [NSApp replyToApplicationShouldTerminate:YES];
        return;
    }
    if (finished == self.updateTask) {
        self.updateTask = nil;
        if (finished.terminationStatus != 0) [self showUpdateFailure];
        if (self.launcher.running) return; // Cancel/failure before Stop keeps the original owner.
        [NSApp terminate:nil];
        return;
    }
    if (finished != self.launcher) return;
    if (self.updateTask) {
        if (self.updateTask.running) {
            self.launcher = self.updateTask; // Its verified Python exec becomes the new supervisor.
            self.updateTask = nil;
        }
        return; // A completed updater's queued handler reports its outcome.
    }
    if (finished.terminationStatus != 0) {
        NSAlert *alert = [NSAlert new];
        alert.messageText = @"AI Station could not start";
        alert.informativeText = @"Check the application package and Docker Desktop, then open AI Station again.";
        alert.icon = stationIcon();
        [alert runModal];
    }
    [NSApp terminate:nil];
}
- (NSURL *)retainedResources {
    NSString *identity = self.bootstrapIdentity;
    if (!identity) {
        NSData *data = [NSData dataWithContentsOfURL:[self.resources URLByAppendingPathComponent:@"desktop-manifest.json"] options:NSDataReadingMappedIfSafe error:NULL];
        id raw = data && data.length <= 8 * 1024 * 1024 ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
        NSDictionary *manifest = [raw isKindOfClass:NSDictionary.class] ? raw : @{};
        identity = field(manifest, @"bundle_id", @"");
    }
    NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet];
    if (identity.length != 64 || [identity rangeOfCharacterFromSet:invalid].location != NSNotFound) return self.resources;
    self.bootstrapIdentity = identity; // Remains usable after a download disk is unmounted.
    NSString *home = NSProcessInfo.processInfo.environment[@"HOME"] ?: NSHomeDirectory();
    NSString *path = [[home stringByAppendingPathComponent:@"Library/Application Support/AI Station/releases"] stringByAppendingPathComponent:identity];
    struct stat info;
    if (lstat(path.fileSystemRepresentation, &info) || !S_ISDIR(info.st_mode) || info.st_uid != getuid() || (info.st_mode & 0022)) return self.resources;
    return [NSURL fileURLWithPath:path isDirectory:YES];
}
- (NSTask *)taskAt:(NSURL *)root arguments:(NSArray<NSString *> *)arguments {
    NSTask *task = [NSTask new];
    task.executableURL = [root URLByAppendingPathComponent:@"python/bin/python3.12"];
    task.arguments = [@[@"-IB", [root URLByAppendingPathComponent:@"scripts/desktop.py"].path] arrayByAddingObjectsFromArray:arguments];
    task.currentDirectoryURL = root;
    return task;
}
- (void)openStation:(id)sender {
    if (self.stopping || self.updateTask) return;
    NSTask *task = [self taskAt:[self retainedResources] arguments:@[]];
    __weak StationDelegate *weakSelf = self;
    task.terminationHandler = ^(NSTask *finished) {
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf.reopenTasks removeObject:finished]; });
    };
    NSError *error = nil;
    if ([task launchAndReturnError:&error]) [self.reopenTasks addObject:task];
}
- (void)installUpdate:(id)sender {
    if (self.stopping || self.updateTask || !self.launcher.running) return;
    NSOpenPanel *panel = updatePanel();
    if ([panel runModal] != NSModalResponseOK || !panel.URL || self.stopping || !self.launcher.running) return;
    NSTask *task = [self taskAt:[self retainedResources] arguments:@[@"--install-update", panel.URL.path, @"--background"]];
    __weak StationDelegate *weakSelf = self;
    task.terminationHandler = ^(NSTask *finished) {
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf taskFinished:finished]; });
    };
    self.updateTask = task;
    if (![task launchAndReturnError:NULL]) {
        self.updateTask = nil;
        [self showUpdateFailure];
    }
}
- (BOOL)validateMenuItem:(NSMenuItem *)item {
    if (item.action == @selector(openStation:) || item.action == @selector(installUpdate:) || item.action == @selector(manageBackups:))
        return !self.stopping && self.updateTask == nil && self.launcher.running;
    return YES;
}
- (void)manageBackups:(id)sender {
    if (self.stopping || self.updateTask || !self.launcher.running) return;
    NSTask *task = [self taskAt:[self retainedResources] arguments:@[@"--manage-backups", @"--background"]];
    __weak StationDelegate *weakSelf = self;
    task.terminationHandler = ^(NSTask *finished) {
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf taskFinished:finished]; });
    };
    self.updateTask = task;
    if (![task launchAndReturnError:NULL]) {
        self.updateTask = nil;
        [self showUpdateFailure];
    }
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.resources = NSBundle.mainBundle.resourceURL;
    [self retainedResources];
    self.reopenTasks = [NSMutableArray new];
    self.launcher = [self taskAt:self.resources arguments:@[@"--background"]];
    __weak StationDelegate *weakSelf = self;
    self.launcher.terminationHandler = ^(NSTask *finished) {
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf taskFinished:finished]; });
    };
    NSError *error = nil;
    if (![self.launcher launchAndReturnError:&error]) {
        NSAlert *alert = [NSAlert new];
        alert.messageText = @"AI Station could not open";
        alert.informativeText = @"The application package is incomplete. Reinstall the application while keeping its saved data.";
        [alert runModal];
        [NSApp terminate:nil];
    }
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)visible {
    [self openStation:nil];
    return YES;
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    if (!self.launcher.running && !self.updateTask.running) return NSTerminateNow;
    self.stopping = YES;
    if (self.updateTask.running && self.updateTask != self.launcher) [self.updateTask terminate];
    if (self.launcher.running) [self.launcher terminate]; // Only retained NSTask children.
    return NSTerminateLater;
}
@end
static StationDelegate *stationDelegate;

static NSTask *neutralTask(BOOL immediate) {
    NSTask *task = [NSTask new];
    task.executableURL = [NSURL fileURLWithPath:immediate ? @"/usr/bin/true" : @"/bin/sleep"];
    task.arguments = immediate ? @[] : @[@"30"];
    if (![task launchAndReturnError:NULL]) return nil;
    if (immediate) [task waitUntilExit];
    return task;
}

static int updateOwnershipSmoke(void) {
    prepareUI(NSApplicationActivationPolicyAccessory);
    NSMutableArray<NSTask *> *owned = [NSMutableArray new];
    @try {
        NSTask *old = neutralTask(NO);
        if (old) [owned addObject:old];
        NSTask *canceled = neutralTask(YES);
        if (canceled) [owned addObject:canceled];
        NSTask *unrelated = neutralTask(NO);
        if (unrelated) [owned addObject:unrelated];
        if (!old || !canceled || !unrelated) return 1;
        StationDelegate *entry = [StationDelegate new];
        entry.launcher = old;
        entry.updateTask = canceled;
        [entry taskFinished:canceled];
        if (!old.running || entry.updateTask || !unrelated.running) return 1;
        [old terminate]; [old waitUntilExit];
        NSTask *updated = neutralTask(NO);
        if (!updated) return 1;
        [owned addObject:updated];
        entry.updateTask = updated;
        [entry taskFinished:old];
        if (entry.launcher != updated || entry.updateTask || !updated.running || !unrelated.running) return 1;
        if ([entry applicationShouldTerminate:NSApp] != NSTerminateLater) return 1;
        [updated waitUntilExit];
        if (updated.running || !unrelated.running) return 1;
        NSTask *oldAgain = neutralTask(NO), *updateAgain = neutralTask(NO);
        if (oldAgain) [owned addObject:oldAgain];
        if (updateAgain) [owned addObject:updateAgain];
        if (!oldAgain || !updateAgain) return 1;
        entry.launcher = oldAgain; entry.updateTask = updateAgain; entry.stopping = NO;
        if ([entry applicationShouldTerminate:NSApp] != NSTerminateLater) return 1;
        [oldAgain waitUntilExit]; [updateAgain waitUntilExit];
        if (oldAgain.running || updateAgain.running || !unrelated.running) return 1;
        answer(@"native-update-owned-handoff-passed");
        return 0;
    } @finally {
        for (NSTask *task in owned) {
            if (task.running) [task terminate];
            [task waitUntilExit];
        }
    }
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSString *mode = argc > 1 ? [NSString stringWithUTF8String:argv[1]] : @"";
        if ([mode isEqual:@"--native-dialog"]) return showDialog(NO);
        if ([mode isEqual:@"--native-running"]) return showDialog(YES);
        if ([mode isEqual:@"--native-progress"]) return progressWindow(NO, NO);
        if ([mode isEqual:@"--native-ui-smoke"]) return progressWindow(YES, NO);
        if ([mode isEqual:@"--native-backup-progress-smoke"]) return progressWindow(NO, YES);
        if ([mode isEqual:@"--native-update-smoke"]) return updateChooserSmoke();
        if ([mode isEqual:@"--native-backups"]) return backupDialog(NO, NO);
        if ([mode isEqual:@"--native-backup-folder"]) return backupDialog(YES, NO);
        if ([mode isEqual:@"--native-backup-smoke"]) return backupDialog(YES, YES);
        if ([mode isEqual:@"--native-update-ownership-smoke"]) return updateOwnershipSmoke();
        NSSet *allowed = [NSSet setWithArray:@[@"--console", @"--background", @"--status", @"--stop", @"--package-check", @"--manage-backups"]];
        NSMutableArray *arguments = [NSMutableArray new];
        for (int i = 1; i < argc; i++) {
            NSString *value = [NSString stringWithUTF8String:argv[i]];
            if (![allowed containsObject:value]) return 2;
            [arguments addObject:value];
        }
        if (arguments.count) {
            StationDelegate *entry = [StationDelegate new];
            NSTask *task = [entry taskAt:NSBundle.mainBundle.resourceURL arguments:arguments];
            if (![task launchAndReturnError:NULL]) return 1;
            [task waitUntilExit];
            return task.terminationStatus;
        }
        prepareUI(NSApplicationActivationPolicyRegular);
        stationDelegate = [StationDelegate new];
        NSMenu *menu = [NSMenu new];
        NSMenuItem *item = [NSMenuItem new];
        [menu addItem:item];
        NSMenu *application = [[NSMenu alloc] initWithTitle:@"AI Station"];
        NSMenuItem *open = [[NSMenuItem alloc] initWithTitle:@"Open AI Station" action:@selector(openStation:) keyEquivalent:@"o"];
        open.target = stationDelegate;
        [application addItem:open];
        NSMenuItem *update = [[NSMenuItem alloc] initWithTitle:@"Install Update…" action:@selector(installUpdate:) keyEquivalent:@""];
        update.target = stationDelegate;
        [application addItem:update];
        NSMenuItem *backups = [[NSMenuItem alloc] initWithTitle:@"Backups and Restore…" action:@selector(manageBackups:) keyEquivalent:@""];
        backups.target = stationDelegate;
        [application addItem:backups];
        [application addItem:NSMenuItem.separatorItem];
        [application addItemWithTitle:@"Quit AI Station" action:@selector(terminate:) keyEquivalent:@"q"];
        item.submenu = application;
        NSApp.mainMenu = menu;
        NSApp.delegate = stationDelegate;
        [NSApp run];
        return 0;
    }
}
