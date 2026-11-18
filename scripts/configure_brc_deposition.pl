#!/usr/bin/env perl
# Opt-in BrC diagnostics for a generated v14.8 HISTORY.rc; no physics edits.
use strict;
use warnings;
use Getopt::Long qw(GetOptions);
my ($file, $short, $monthly) = ('', 0, 0);
GetOptions('history=s' => \$file, 'short-test-hourly' => \$short, 'monthly' => \$monthly)
    or die "Usage: $0 --history HISTORY.rc [--short-test-hourly]\n";
$file && !@ARGV or die "Usage: $0 --history HISTORY.rc [--short-test-hourly]\n";
open my $in, '<', $file or die "$file: $!\n";
local $/; my $text = <$in>; close $in;
my @aerosol = qw(PBRCPOA NPBRCPOA DBRCPOA BRCSOA PWTC SWTC FSOAS FOCPI FOCPO);
# DBRCPOA retains dry deposition but has no wet removal.
my @wet = grep { $_ ne 'DBRCPOA' } @aerosol;
my @family = (@aerosol, 'FSOAP');
my %fields = (
 BrCDryDep => [map { my $p = $_; map { "${p}_$_" } @aerosol } qw(DryDep DryDepVel)],
 BrCWetLoss => [map { my $p = $_; map { "${p}_$_" } @wet } qw(WetLossConv WetLossConvFrac WetLossLS)],
 BrCProcessBudget => [
  (map { my $p = $_; map { "Budget${p}Full_$_" } @family } qw(EmisDryDep Chemistry Transport Mixing Convection)),
  (map { "BudgetWetDepFull_$_" } @wet)
 ],
);
# Never replace unrelated collections or manually authored blocks with these names.
$text =~ s/\n# BEGIN managed BrC deposition\n.*?# END managed BrC deposition\n/\n/s;
for my $name (keys %fields) {
    $text !~ /^\s*\Q$name\E\./m or die "Unmanaged $name block exists; refusing overwrite\n";
}
$text =~ s{(^COLLECTIONS:.*?^::)}{
 my $decl = $1;
 $decl =~ s/^\s*'(?:BrCDryDep|BrCWetLoss|BrCProcessBudget)',?\s*\n//mg;
 $decl =~ s/^::/             'BrCDryDep',\n             'BrCWetLoss',\n             'BrCProcessBudget',\n::/m;
 $decl;
}mse or die "Missing COLLECTIONS declaration\n";
die "Cannot combine --monthly and --short-test-hourly\n" if $short && $monthly;
my $cadence = $monthly ? '00000100 000000' : $short ? '00000000 010000' : '00000001 000000';
# A blank line after an inactive block can make Classic's HISTORY reader
# skip the next block. Keep the appended boundary free of blank lines.
$text =~ s/\s*\z/\n/;
my $managed = "";
$managed .= "# BEGIN managed BrC deposition\n";
$managed .= "# Dry flux: molec cm-2 s-1; velocity: cm s-1; wet loss/budgets: kg s-1.\n";
$managed .= "# FSOAP has no deposition flags. EmisDryDep is a combined operator budget.\n";
for my $name (qw(BrCDryDep BrCWetLoss BrCProcessBudget)) {
 $managed .= "  $name.template: '%y4%m2%d2_%h2%n2z.nc4',\n";
 $managed .= "  $name.frequency: $cadence\n  $name.duration: $cadence\n";
 $managed .= "  $name.mode: 'time-averaged'\n";
 my @f = @{$fields{$name}};
 $managed .= "  $name.fields: '" . shift(@f) . "',\n";
 $managed .= join('', map { "                    '$_',\n" } @f);
 $managed .= "::\n";
}
$managed .= "# END managed BrC deposition\n";
# Insert before BC's first active property, preserving its complete definition.
# COLLECTIONS ordering alone does not control Classic startup output.
if ($text =~ /^[ \t]*BoundaryConditions\./m) {
 $text =~ s/^([ \t]*BoundaryConditions\.)/$managed$1/m;
} else {
 $text .= $managed;
}
# Replace only after all validation; preserve permissions and retain a backup.
my $tmp = "$file.brc.tmp";
!-e $tmp or die "Temporary file already exists: $tmp\n";
open my $out, '>', $tmp or die "$tmp: $!\n";
print {$out} $text or die "Write failed: $!\n";
close $out or die "Close failed: $!\n";
chmod((stat($file))[2] & 07777, $tmp) or die "chmod: $!\n";
if (!-e "$file.before_brc") {
 require File::Copy; File::Copy::copy($file, "$file.before_brc") or die "Backup failed: $!\n";
}
rename $tmp, $file or die "Rename failed: $!\n";
print 'Enabled ' . join(', ', map { "$_ (" . scalar(@{$fields{$_}}) . ')' }
    qw(BrCDryDep BrCWetLoss BrCProcessBudget)) . "; cadence $cadence\n";
